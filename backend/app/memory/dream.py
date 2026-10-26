"""Dreaming (MEM-4): consolidation per entity and scope, nightly and on demand.

Each (entity, scope) pair is dreamt on its own, with only that scope's conclusions, so derived conclusions
and summary cards never mix knowledge from scopes with different readers (MEM-7).
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import client as ai
from app.auth.models import Role, User
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.jobs import queue
from app.memory import prompts
from app.memory.extract import embed_texts, is_suppressed, normalize, scope_columns
from app.memory.models import (
    ConclusionKind,
    ConclusionStatus,
    MemCard,
    MemConclusion,
    MemDreamRun,
    MemEntity,
    MemPremise,
    ScopeKind,
)
from app.projects.models import Project
from app.teams.models import Team

log = logging.getLogger(__name__)

PAIR_LIMIT = 200
MAX_OPS = 20
TEXT_MAX = 500
CARD_MAX = 2000
TICK_SECONDS = 3600
MIN_HOURS_BETWEEN = 20
RUNNING_STALE = timedelta(hours=6)
ERROR_MAX = 500


class _Replace(BaseModel):
    ids: list[str]
    text: str


class _Deduce(BaseModel):
    premises: list[str]
    text: str


class _Induce(BaseModel):
    premises: list[str]
    text: str
    confidence: float


class DreamOut(BaseModel):
    replace: list[_Replace] = []
    deduce: list[_Deduce] = []
    induce: list[_Induce] = []
    card: str = ""


def utcnow() -> datetime:
    return datetime.now(UTC)


def _scope_where(model, scope):
    kind, ref = scope
    return and_(
        model.scope_kind == kind,
        model.scope_team_id.is_not_distinct_from(ref if kind == ScopeKind.team else None),
        model.scope_project_id.is_not_distinct_from(ref if kind == ScopeKind.project else None),
    )


async def _pairs(db: AsyncSession) -> list[tuple[uuid.UUID, tuple]]:
    """(entity, scope) pairs whose conclusions changed since their card was refreshed, or that have no card."""
    card = MemCard
    rows = await db.execute(
        select(MemConclusion.entity_id, MemConclusion.scope_kind, MemConclusion.scope_team_id,
               MemConclusion.scope_project_id)
        .outerjoin(
            card,
            and_(
                card.entity_id == MemConclusion.entity_id,
                card.scope_kind == MemConclusion.scope_kind,
                card.scope_team_id.is_not_distinct_from(MemConclusion.scope_team_id),
                card.scope_project_id.is_not_distinct_from(MemConclusion.scope_project_id),
            ),
        )
        .where(or_(card.id.is_(None), MemConclusion.updated_at > card.refreshed_at))
        .distinct()
    )
    return [(e, (ScopeKind(k), t or p)) for e, k, t, p in rows]


async def _scope_label(db: AsyncSession, scope) -> str:
    kind, ref = scope
    if kind == ScopeKind.team:
        team = await db.get(Team, ref)
        return f"team {team.name}" if team else "team"
    if kind == ScopeKind.project:
        project = await db.get(Project, ref)
        return f"project {project.key}" if project else "project"
    return "organization"


def _clip(text: str, limit: int) -> str:
    return " ".join(text.replace("\x00", "").split())[:limit]


async def _derive(
    db: AsyncSession, entity: MemEntity, scope, kind: ConclusionKind, text: str, premises: list[MemConclusion],
    existing: set[str], confidence: float | None = None,
) -> MemConclusion | None:
    text = _clip(text, TEXT_MAX)
    if not text or normalize(text) in existing:
        return None
    model, vectors = await embed_texts(db, [text])
    vector = vectors[0] if vectors else None
    for p in premises:  # never re-derive what a human deleted or corrected from these sources
        if await is_suppressed(db, p.source_kind, p.source_id, entity.id, text, vector, model):
            return None
    row = MemConclusion(
        id=uuid.uuid4(), entity_id=entity.id, text=text, kind=kind, confidence=confidence,
        source_kind=None, source_id=None, source_label=None, embedding=vector,
        embedding_model=model if vector else None, **scope_columns(scope),
    )
    db.add(row)
    await db.flush()
    db.add_all(MemPremise(conclusion_id=row.id, premise_id=p.id) for p in premises)
    existing.add(normalize(text))
    return row


async def _dream_pair(db: AsyncSession, entity: MemEntity, scope, stats: dict) -> None:
    rows = (
        await db.execute(
            select(MemConclusion)
            .where(MemConclusion.entity_id == entity.id, MemConclusion.status == ConclusionStatus.active,
                   _scope_where(MemConclusion, scope))
            .order_by(MemConclusion.pinned.desc(), MemConclusion.created_at.desc())
            .limit(PAIR_LIMIT)
        )
    ).scalars().all()
    card = (
        await db.execute(select(MemCard).where(MemCard.entity_id == entity.id, _scope_where(MemCard, scope)))
    ).scalar_one_or_none()
    if not rows:
        if card is not None:
            await db.delete(card)
        return
    messages = prompts.dreaming_messages(entity.name, await _scope_label(db, scope), card.summary_md if card else "", rows)
    out = ai.parse_json(await ai.complete(db, "dreaming", messages), DreamOut)
    by_id = {f"C{i}": c for i, c in enumerate(rows, start=1)}
    existing = {normalize(r.text) for r in rows}

    def pick(ids: list[str]) -> list[MemConclusion]:
        found = []
        for i in ids:
            c = by_id.get(str(i).strip())
            if c is not None and c not in found:
                found.append(c)
        return found

    for op in out.replace[:MAX_OPS]:
        targets = [c for c in pick(op.ids) if not c.pinned and c.status == ConclusionStatus.active]
        if not targets:
            stats["dropped"] += 1
            continue
        for t in targets:
            existing.discard(normalize(t.text))
        new = await _derive(db, entity, scope, ConclusionKind.deduced, op.text, targets, existing)
        if new is None:
            stats["dropped"] += 1
            continue
        for t in targets:
            t.status = ConclusionStatus.superseded
            t.superseded_by_id = new.id
        stats["replaced"] += len(targets)
    for op in out.deduce[:MAX_OPS]:
        premises = pick(op.premises)
        new = await _derive(db, entity, scope, ConclusionKind.deduced, op.text, premises, existing) if premises else None
        stats["deduced" if new else "dropped"] += 1
    for op in out.induce[:MAX_OPS]:
        premises = pick(op.premises)
        ok = len(premises) >= 2 and 0.0 <= op.confidence <= 1.0
        new = (
            await _derive(db, entity, scope, ConclusionKind.induced, op.text, premises, existing, op.confidence)
            if ok else None
        )
        stats["induced" if new else "dropped"] += 1
    dropped_extra = max(0, len(out.replace) - MAX_OPS) + max(0, len(out.deduce) - MAX_OPS) + max(
        0, len(out.induce) - MAX_OPS
    )
    stats["dropped"] += dropped_extra
    summary = out.card.replace("\x00", "").strip()[:CARD_MAX]
    if card is None:
        card = MemCard(entity_id=entity.id, **scope_columns(scope))
        db.add(card)
    card.summary_md = summary
    card.conclusion_ids = [str(r.id) for r in rows]
    card.refreshed_at = func.now()
    stats["cards"] += 1


async def _set_run(run_id: uuid.UUID, **values) -> None:
    async with SessionLocal() as s:
        run = await s.get(MemDreamRun, run_id)
        if run is not None:
            for k, v in values.items():
                setattr(run, k, v)
            await s.commit()


@queue.register("mem.dream")
async def dream(db: AsyncSession, payload: dict) -> None:
    run_id = uuid.UUID(payload["run_id"]) if payload.get("run_id") else None
    if run_id is None:
        async with SessionLocal() as s:
            run = MemDreamRun(id=uuid.uuid4(), trigger=payload.get("trigger", "scheduled"))
            s.add(run)
            await s.commit()
            run_id = run.id
    stats = {"pairs": 0, "replaced": 0, "deduced": 0, "induced": 0, "cards": 0, "dropped": 0, "failed_pairs": 0}
    try:
        for entity_id, scope in await _pairs(db):
            entity = await db.get(MemEntity, entity_id)
            if entity is None:
                continue
            stats["pairs"] += 1
            try:
                async with db.begin_nested():
                    await _dream_pair(db, entity, scope, stats)
            except ai.AiNotConfigured:
                raise
            except Exception:
                log.warning("dreaming failed for entity %s", entity_id, exc_info=True)
                stats["failed_pairs"] += 1
    except ai.AiNotConfigured:
        await db.rollback()
        await _set_run(run_id, status="failed", error="not_configured", stats=stats, finished_at=utcnow())
        return
    except Exception as exc:  # noqa: BLE001 - recorded on the run; the job is not retried
        await db.rollback()
        await _set_run(run_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:ERROR_MAX], stats=stats,
                       finished_at=utcnow())
        return
    run = await db.get(MemDreamRun, run_id)
    run.status = "done"
    run.stats = stats
    run.finished_at = utcnow()


@queue.register("mem.dream_tick")
async def dream_tick(db: AsyncSession, payload: dict) -> None:
    """Hourly: starts the nightly dream in the configured UTC hour, at most once per 20 hours."""
    now = utcnow()
    if now.hour != get_settings().memory_dream_hour_utc:
        return
    recent = await db.scalar(
        select(MemDreamRun.id).where(MemDreamRun.started_at > now - timedelta(hours=MIN_HOURS_BETWEEN)).limit(1)
    )
    if recent is None:
        await queue.enqueue(db, "mem.dream", {"trigger": "scheduled"}, dedupe_key="mem.dream")


queue.register_periodic("mem.dream_tick", TICK_SECONDS)


async def start_dream(db: AsyncSession, user: User) -> MemDreamRun:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    running = await db.scalar(
        select(MemDreamRun.id).where(MemDreamRun.status == "running",
                                     MemDreamRun.started_at > utcnow() - RUNNING_STALE).limit(1)
    )
    if running is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "dream_running")
    run = MemDreamRun(id=uuid.uuid4(), trigger="manual", requested_by=user.id)
    db.add(run)
    await db.flush()
    await queue.enqueue(db, "mem.dream", {"run_id": str(run.id)}, dedupe_key="mem.dream")
    return run

