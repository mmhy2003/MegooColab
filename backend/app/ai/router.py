import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import Date, cast, func, select
from sqlalchemy.exc import IntegrityError

from app.ai import client as ai
from app.ai.models import AiJobModel, AiProvider, AiUsage
from app.ai.schemas import (
    JobModelIn,
    JobModelOut,
    ProviderIn,
    ProviderOut,
    ProviderPatch,
    TestResult,
    UsageRow,
)
from app.audit import service as audit
from app.auth.deps import AdminUser
from app.core.crypto import encrypt
from app.core.db import DbSession
from app.core.events import Event, publish
from app.jobs import queue

router = APIRouter(prefix="/api/admin/ai", tags=["ai"])

ERROR_LIMIT = 300


def _out(p: AiProvider) -> ProviderOut:
    return ProviderOut(id=p.id, name=p.name, kind=p.kind, api_base=p.api_base, has_key=bool(p.api_key_enc))


async def _provider(db, provider_id: uuid.UUID) -> AiProvider:
    p = await db.get(AiProvider, provider_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "provider_not_found")
    return p


async def _flush_unique(db) -> None:
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "provider_name_taken") from None


@router.get("/providers")
async def list_providers(db: DbSession, _admin: AdminUser) -> list[ProviderOut]:
    rows = (await db.execute(select(AiProvider).order_by(AiProvider.name))).scalars()
    return [_out(p) for p in rows]


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(body: ProviderIn, db: DbSession, admin: AdminUser) -> ProviderOut:
    p = AiProvider(
        name=body.name,
        kind=body.kind,
        api_base=body.api_base or None,
        api_key_enc=encrypt(body.api_key) if body.api_key else None,
    )
    db.add(p)
    await _flush_unique(db)
    await audit.record(db, "ai.provider.created", actor_id=admin.id, target_type="ai_provider", target_id=p.id,
                       data={"name": p.name, "kind": p.kind})
    return _out(p)


@router.patch("/providers/{provider_id}")
async def update_provider(provider_id: uuid.UUID, body: ProviderPatch, db: DbSession, admin: AdminUser) -> ProviderOut:
    p = await _provider(db, provider_id)
    fields = body.model_fields_set
    if body.name is not None:
        p.name = body.name
    if body.kind is not None:
        p.kind = body.kind
    if "api_base" in fields:
        p.api_base = body.api_base or None
    if "api_key" in fields and body.api_key is not None:
        p.api_key_enc = encrypt(body.api_key) if body.api_key else None
    await _flush_unique(db)
    await audit.record(db, "ai.provider.updated", actor_id=admin.id, target_type="ai_provider", target_id=p.id,
                       data={"fields": sorted(fields - {"api_key"}) + (["api_key"] if "api_key" in fields else [])})
    return _out(p)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: uuid.UUID, db: DbSession, admin: AdminUser) -> Response:
    p = await _provider(db, provider_id)
    in_use = (await db.execute(select(AiJobModel.job).where(AiJobModel.provider_id == p.id).limit(1))).first()
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT, "provider_in_use")
    await db.delete(p)
    await audit.record(db, "ai.provider.deleted", actor_id=admin.id, target_type="ai_provider", target_id=provider_id,
                       data={"name": p.name})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _known(job: str) -> None:
    if job not in ai.JOBS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown_job")


@router.get("/jobs")
async def list_jobs(db: DbSession, _admin: AdminUser) -> list[JobModelOut]:
    rows = {r.job: r for r in (await db.execute(select(AiJobModel))).scalars()}
    return [
        JobModelOut(job=j, provider_id=rows[j].provider_id if j in rows else None, model=rows[j].model if j in rows else "")
        for j in ai.JOBS
    ]


@router.put("/jobs/{job}")
async def put_job(job: str, body: JobModelIn, db: DbSession, admin: AdminUser) -> JobModelOut:
    _known(job)
    if body.provider_id is not None:
        await _provider(db, body.provider_id)
    before = await ai.configured_model(db, job)
    row = await db.get(AiJobModel, job, with_for_update=True)
    if row is None:
        row = AiJobModel(job=job)
        db.add(row)
    row.provider_id = body.provider_id
    row.model = body.model.strip()
    await db.flush()
    await audit.record(db, "ai.job.updated", actor_id=admin.id, target_type="ai_job",
                       data={"job": job, "provider_id": str(body.provider_id) if body.provider_id else None,
                             "model": row.model})
    if job == "embeddings" and await ai.configured_model(db, job) != before:
        await on_embeddings_model_changed(db)
    return JobModelOut(job=job, provider_id=row.provider_id, model=row.model)


async def on_embeddings_model_changed(db) -> None:
    await publish(db, Event(type="ai.embeddings_model_changed"))
    # every document is re-embedded with the new model (handled by the kb.reembed_all job)
    await queue.enqueue(db, "kb.reembed_all", {}, dedupe_key="kb.reembed_all")


@router.post("/jobs/{job}/test")
async def test_job(job: str, db: DbSession, _admin: AdminUser) -> TestResult:
    _known(job)
    model = await ai.current_model(db, job)
    try:
        model, _ = await ai.embed(db, ["ping"], job=job)
    except ai.AiNotConfigured:
        return TestResult(ok=False, model=None, error="not_configured")
    except Exception as exc:  # noqa: BLE001 - shown to the admin
        message = f"{type(exc).__name__}: {exc}"
        resolved = await ai._resolve(db, job)
        key = await ai.provider_key(db, resolved[1].id) if resolved else None
        if key:
            message = message.replace(key, "***")
        return TestResult(ok=False, model=model, error=message[:ERROR_LIMIT])
    return TestResult(ok=True, model=model, error=None)


@router.get("/usage")
async def usage(db: DbSession, _admin: AdminUser, days: int = Query(30, ge=1, le=365)) -> list[UsageRow]:
    day = cast(func.date_trunc("day", AiUsage.created_at), Date).label("day")
    rows = await db.execute(
        select(
            day,
            AiUsage.job,
            AiUsage.model,
            func.count().label("calls"),
            func.count().filter(AiUsage.ok.is_(False)).label("failures"),
            func.coalesce(func.sum(AiUsage.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AiUsage.output_tokens), 0).label("output_tokens"),
            func.sum(AiUsage.cost_usd).label("cost_usd"),
        )
        .where(AiUsage.created_at >= func.now() - timedelta(days=days))
        .group_by(day, AiUsage.job, AiUsage.model)
        .order_by(day.desc(), AiUsage.job, AiUsage.model)
    )
    return [UsageRow(**r._mapping) for r in rows]

