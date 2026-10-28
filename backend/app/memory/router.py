"""Memory REST API: browse entities and conclusions, sources and reasoning chains, correct/delete/pin, ask,
products, and dreaming (MEM-5, MEM-8). Everything is filtered by the caller's readable scopes."""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun
from app.audit import service as audit
from app.auth.deps import AdminUser, AuthedUser
from app.auth.models import Role, User
from app.core.db import DbSession
from app.kb.models import KbDocument
from app.memory import answer as answering
from app.memory import dream as dreaming
from app.memory import entities
from app.memory.access import ReadableScopes, can_edit_scope, readable_scopes
from app.memory.extract import clear_cards, embed_texts, scope_columns
from app.memory.models import (
    ConclusionKind,
    ConclusionStatus,
    EntityKind,
    MemCard,
    MemConclusion,
    MemDreamRun,
    MemEntity,
    MemPremise,
    MemSuppression,
    ScopeKind,
)
from app.memory.schemas import (
    AskIn,
    AskOut,
    ChainNode,
    ConclusionDetail,
    ConclusionOut,
    ConclusionPage,
    CorrectIn,
    DreamRunOut,
    MemCardOut,
    MemEntityDetail,
    MemEntityOut,
    MemScopeOut,
    MemSourceOut,
    PinIn,
    ProductIn,
    ProductPatch,
)
from app.projects.access import get_project_for
from app.projects.models import Project
from app.ratelimit.deps import check_ai
from app.tasks.models import Comment, Task
from app.teams.models import Team
from app.workflow.models import StepReview

router = APIRouter(tags=["memory"])

CHAIN_DEPTH = 5
PAGE_MAX = 100


# -- shaping -----------------------------------------------------------------------------------------


async def _scope_out(db: AsyncSession, kind: str, team_id, project_id) -> MemScopeOut:
    if kind == ScopeKind.team:
        team = await db.get(Team, team_id)
        return MemScopeOut(kind=kind, id=team_id, name=team.name if team else "Team")
    if kind == ScopeKind.project:
        project = await db.get(Project, project_id)
        return MemScopeOut(kind=kind, id=project_id, name=f"{project.key} — {project.name}" if project else "Project")
    return MemScopeOut(kind="org", id=None, name="Organization")


async def _task_link(db: AsyncSession, task_id) -> str | None:
    task = await db.get(Task, task_id) if task_id else None
    project = await db.get(Project, task.project_id) if task else None
    return f"/projects/{project.key}/tasks/{task.number}" if project else None


async def _source_link(db: AsyncSession, kind: str, sid) -> str | None:
    if kind == "task":
        return await _task_link(db, sid)
    if kind == "comment":
        row = await db.get(Comment, sid)
        return await _task_link(db, row.task_id) if row else None
    if kind == "run":
        row = await db.get(AgentRun, sid)
        return await _task_link(db, row.task_id) if row else None
    if kind == "review":
        row = await db.get(StepReview, sid)
        return await _task_link(db, row.task_id) if row else None
    if kind == "kb_document":
        return f"/kb/doc/{sid}" if await db.get(KbDocument, sid) else None
    return None


async def conclusion_out(db: AsyncSession, user: User, c: MemConclusion) -> ConclusionOut:
    entity = await db.get(MemEntity, c.entity_id)
    source = None
    if c.source_kind:
        source = MemSourceOut(kind=c.source_kind, label=c.source_label or c.source_kind,
                              link=await _source_link(db, c.source_kind, c.source_id))
    return ConclusionOut(
        id=c.id, entity_id=c.entity_id, entity_name=entity.name if entity else "", text=c.text, kind=c.kind,
        confidence=c.confidence, status=c.status, pinned=c.pinned,
        scope=await _scope_out(db, c.scope_kind, c.scope_team_id, c.scope_project_id), source=source,
        created_at=c.created_at, can_edit=await can_edit_scope(db, user, c.scope),
    )


# -- visibility --------------------------------------------------------------------------------------


async def _visible_entities_clause(db: AsyncSession, user: User):
    """Team and project entities follow access; the org, people, agents and products are listed for all."""
    if user.role == Role.admin:
        return None
    scopes = await readable_scopes(db, user)
    return or_(
        MemEntity.kind.in_([EntityKind.org, EntityKind.user, EntityKind.agent, EntityKind.product]),
        MemEntity.team_id.in_(scopes.team_ids),
        MemEntity.project_id.in_(scopes.project_ids),
    )


async def _entity_for(db: AsyncSession, user: User, entity_id: uuid.UUID) -> MemEntity:
    clause = await _visible_entities_clause(db, user)
    stmt = select(MemEntity).where(MemEntity.id == entity_id)
    if clause is not None:
        stmt = stmt.where(clause)
    entity = (await db.execute(stmt)).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entity_not_found")
    return entity


async def _conclusion_for(db: AsyncSession, user: User, cid: uuid.UUID, *, edit: bool = False) -> MemConclusion:
    scopes = await readable_scopes(db, user)
    c = (
        await db.execute(select(MemConclusion).where(MemConclusion.id == cid, scopes.clause(MemConclusion)))
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conclusion_not_found")
    if edit and not await can_edit_scope(db, user, c.scope):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    return c


async def _counts(db: AsyncSession, scopes: ReadableScopes) -> dict[uuid.UUID, int]:
    rows = await db.execute(
        select(MemConclusion.entity_id, func.count())
        .where(MemConclusion.status == ConclusionStatus.active, scopes.clause(MemConclusion))
        .group_by(MemConclusion.entity_id)
    )
    return dict(rows.all())


def _entity_out(e: MemEntity, count: int) -> MemEntityOut:
    return MemEntityOut(id=e.id, kind=e.kind, name=e.name, description=e.description or "", conclusion_count=count)


# -- entities ----------------------------------------------------------------------------------------


@router.get("/api/memory/entities")
async def list_entities(
    user: AuthedUser, db: DbSession, kind: EntityKind | None = None, q: str | None = Query(None, max_length=200)
) -> list[MemEntityOut]:
    stmt = select(MemEntity).order_by(MemEntity.kind, MemEntity.name)
    clause = await _visible_entities_clause(db, user)
    if clause is not None:
        stmt = stmt.where(clause)
    if kind is not None:
        stmt = stmt.where(MemEntity.kind == kind)
    if q:
        stmt = stmt.where(MemEntity.name.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    counts = await _counts(db, await readable_scopes(db, user))
    return [_entity_out(e, counts.get(e.id, 0)) for e in (await db.execute(stmt)).scalars()]


@router.get("/api/memory/entities/{entity_id}")
async def get_entity(entity_id: uuid.UUID, user: AuthedUser, db: DbSession) -> MemEntityDetail:
    entity = await _entity_for(db, user, entity_id)
    scopes = await readable_scopes(db, user)
    cards = (
        await db.execute(
            select(MemCard).where(MemCard.entity_id == entity.id, scopes.clause(MemCard)).order_by(MemCard.scope_kind)
        )
    ).scalars()
    counts = await _counts(db, scopes)
    return MemEntityDetail(
        entity=_entity_out(entity, counts.get(entity.id, 0)),
        cards=[
            MemCardOut(scope=await _scope_out(db, c.scope_kind, c.scope_team_id, c.scope_project_id),
                       summary_md=c.summary_md, refreshed_at=c.refreshed_at)
            for c in cards if c.summary_md.strip()
        ],
        project_ids=sorted(await entities.product_project_ids(db, entity.id)) if entity.kind == EntityKind.product else [],
    )


def _parse_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        at, cid = cursor.split("|", 1)
        return datetime.fromisoformat(at), uuid.UUID(cid)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_cursor") from None


@router.get("/api/memory/entities/{entity_id}/conclusions")
async def list_conclusions(
    entity_id: uuid.UUID,
    user: AuthedUser,
    db: DbSession,
    status_: str = Query("active", alias="status", pattern="^(active|superseded|deleted|all)$"),
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=PAGE_MAX),
) -> ConclusionPage:
    entity = await _entity_for(db, user, entity_id)
    scopes = await readable_scopes(db, user)
    stmt = select(MemConclusion).where(MemConclusion.entity_id == entity.id, scopes.clause(MemConclusion))
    if status_ != "all":
        stmt = stmt.where(MemConclusion.status == status_)
    after = _parse_cursor(cursor)
    if after is not None:
        at, cid = after
        stmt = stmt.where(or_(MemConclusion.created_at < at, and_(MemConclusion.created_at == at, MemConclusion.id < cid)))
    rows = (
        await db.execute(stmt.order_by(MemConclusion.created_at.desc(), MemConclusion.id.desc()).limit(limit + 1))
    ).scalars().all()
    more = len(rows) > limit
    rows = rows[:limit]
    return ConclusionPage(
        items=[await conclusion_out(db, user, c) for c in rows],
        next_cursor=f"{rows[-1].created_at.isoformat()}|{rows[-1].id}" if more else None,
    )


# -- conclusions -------------------------------------------------------------------------------------


async def _chain(db: AsyncSession, user: User, scopes: ReadableScopes, cid: uuid.UUID, depth: int, seen: set) -> list[ChainNode]:
    if depth == 0:
        return []
    premises = (
        await db.execute(
            select(MemConclusion)
            .join(MemPremise, MemPremise.premise_id == MemConclusion.id)
            .where(MemPremise.conclusion_id == cid, scopes.clause(MemConclusion))
            .order_by(MemConclusion.created_at)
        )
    ).scalars().all()
    nodes = []
    for p in premises:
        if p.id in seen:
            continue
        nodes.append(ChainNode(conclusion=await conclusion_out(db, user, p),
                               premises=await _chain(db, user, scopes, p.id, depth - 1, seen | {p.id})))
    return nodes


@router.get("/api/memory/conclusions/{cid}")
async def get_conclusion(cid: uuid.UUID, user: AuthedUser, db: DbSession) -> ConclusionDetail:
    c = await _conclusion_for(db, user, cid)
    scopes = await readable_scopes(db, user)
    derived = (
        await db.execute(
            select(MemConclusion)
            .join(MemPremise, MemPremise.conclusion_id == MemConclusion.id)
            .where(MemPremise.premise_id == c.id, scopes.clause(MemConclusion))
            .order_by(MemConclusion.created_at)
        )
    ).scalars().all()
    return ConclusionDetail(
        conclusion=await conclusion_out(db, user, c),
        premises=await _chain(db, user, scopes, c.id, CHAIN_DEPTH, {c.id}),
        derived=[await conclusion_out(db, user, d) for d in derived],
    )


async def _suppress(db: AsyncSession, c: MemConclusion) -> None:
    vector = (await db.execute(select(MemConclusion.embedding).where(MemConclusion.id == c.id))).scalar_one()
    db.add(MemSuppression(source_kind=c.source_kind, source_id=c.source_id, entity_id=c.entity_id, text=c.text,
                          embedding=list(vector) if vector is not None else None,
                          embedding_model=c.embedding_model if vector is not None else None))


def _require_active(c: MemConclusion) -> None:
    if c.status != ConclusionStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "conclusion_not_active")


@router.post("/api/memory/conclusions/{cid}/correct")
async def correct_conclusion(cid: uuid.UUID, body: CorrectIn, user: AuthedUser, db: DbSession) -> ConclusionOut:
    c = await _conclusion_for(db, user, cid, edit=True)
    _require_active(c)
    text = " ".join(body.text.split())
    model, vectors = await embed_texts(db, [text])
    new = MemConclusion(
        id=uuid.uuid4(), entity_id=c.entity_id, text=text, kind=ConclusionKind.correction,
        source_kind=c.source_kind, source_id=c.source_id, source_label=c.source_label,
        created_by_user_id=user.id, pinned=c.pinned, embedding=vectors[0] if vectors else None,
        embedding_model=model if vectors else None, **scope_columns(c.scope),
    )
    db.add(new)
    await db.flush()
    db.add(MemPremise(conclusion_id=new.id, premise_id=c.id))
    await _suppress(db, c)
    c.status = ConclusionStatus.superseded
    c.superseded_by_id = new.id
    await clear_cards(db, [c.id])  # a card must not keep summarising the corrected fact
    await audit.record(db, "memory.conclusion.corrected", actor_id=user.id, target_type="mem_conclusion",
                       target_id=c.id, data={"old": c.text, "new": text, "new_id": str(new.id)})
    await db.flush()
    return await conclusion_out(db, user, new)


@router.delete("/api/memory/conclusions/{cid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conclusion(cid: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    c = await _conclusion_for(db, user, cid, edit=True)
    if c.status != ConclusionStatus.deleted:
        await _suppress(db, c)
        c.status = ConclusionStatus.deleted
        await clear_cards(db, [c.id])  # a card must not keep summarising the deleted fact
        await audit.record(db, "memory.conclusion.deleted", actor_id=user.id, target_type="mem_conclusion",
                           target_id=c.id, data={"text": c.text, "entity_id": str(c.entity_id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/memory/conclusions/{cid}/pin")
async def pin_conclusion(cid: uuid.UUID, body: PinIn, user: AuthedUser, db: DbSession) -> ConclusionOut:
    c = await _conclusion_for(db, user, cid, edit=True)
    _require_active(c)
    c.pinned = body.pinned
    await db.flush()
    return await conclusion_out(db, user, c)


# -- ask ---------------------------------------------------------------------------------------------


@router.post("/api/memory/ask")
async def ask(body: AskIn, request: Request, user: AuthedUser, db: DbSession) -> AskOut:
    await check_ai(request)
    project_id = None
    if body.project_key:
        project_id = (await get_project_for(db, user, body.project_key)).id
    result = await answering.answer(db, user, body.question, project_id=project_id)
    return AskOut(answer_md=result.answer_md, cited=[await conclusion_out(db, user, c) for c in result.cited])


# -- products ----------------------------------------------------------------------------------------


@router.post("/api/memory/products", status_code=status.HTTP_201_CREATED)
async def create_product(body: ProductIn, user: AuthedUser, db: DbSession) -> MemEntityOut:
    product = await entities.create_product(db, user, body.name, body.description, body.project_ids)
    return _entity_out(product, 0)


@router.patch("/api/memory/products/{product_id}")
async def update_product(product_id: uuid.UUID, body: ProductPatch, user: AuthedUser, db: DbSession) -> MemEntityOut:
    product = await entities.update_product(db, user, product_id, name=body.name, description=body.description,
                                            project_ids=body.project_ids)
    counts = await _counts(db, await readable_scopes(db, user))
    return _entity_out(product, counts.get(product.id, 0))


@router.delete("/api/memory/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    await entities.delete_product(db, user, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- dreaming ----------------------------------------------------------------------------------------


def _run_out(r: MemDreamRun) -> DreamRunOut:
    return DreamRunOut(id=r.id, trigger=r.trigger, status=r.status, stats=dict(r.stats or {}), error=r.error,
                       started_at=r.started_at, finished_at=r.finished_at)


@router.post("/api/admin/memory/dream", status_code=status.HTTP_201_CREATED)
async def dream_now(admin: AdminUser, db: DbSession) -> DreamRunOut:
    run = await dreaming.start_dream(db, admin)
    await db.refresh(run)
    return _run_out(run)


@router.get("/api/admin/memory/dreams")
async def list_dreams(_admin: AdminUser, db: DbSession) -> list[DreamRunOut]:
    rows = await db.execute(select(MemDreamRun).order_by(MemDreamRun.started_at.desc()).limit(20))
    return [_run_out(r) for r in rows.scalars()]

