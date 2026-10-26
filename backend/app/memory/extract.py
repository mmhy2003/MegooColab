"""Continuous learning (MEM-3): a changed source becomes short conclusions about entities, linked to it.

A conclusion a human deleted or corrected is never learned again from the same source (MEM-8): candidates
matching a suppression (same text, or embeddings within SUPPRESS_DISTANCE) are dropped.
"""

import hashlib
import logging
import math
import re
import uuid

from pydantic import BaseModel
from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import array, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.ai import client as ai
from app.jobs import queue
from app.memory import prompts
from app.memory.models import (
    ConclusionKind,
    ConclusionStatus,
    MemCard,
    MemConclusion,
    MemSourceState,
    MemSuppression,
    ScopeKind,
)
from app.memory.sources import Source, load_source, queue_extract

log = logging.getLogger(__name__)

MAX_CONCLUSIONS = 10
TEXT_MAX = 500
SUPPRESS_DISTANCE = 0.2
RECONCILE_SECONDS = 1800
RECONCILE_LIMIT = 1000


class _Item(BaseModel):
    entity: str
    text: str


class ExtractionOut(BaseModel):
    conclusions: list[_Item] = []


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def cosine_distance(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 1.0
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 1.0
    return 1.0 - sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def scope_columns(scope) -> dict:
    kind, ref = scope
    return {
        "scope_kind": ScopeKind(kind),
        "scope_team_id": ref if kind == ScopeKind.team else None,
        "scope_project_id": ref if kind == ScopeKind.project else None,
    }


async def embed_texts(db: AsyncSession, texts: list[str]) -> tuple[str | None, list[list[float]] | None]:
    """Vectors for new memory text, or (None, None) when embeddings are unavailable (reconciled later)."""
    if not texts:
        return None, None
    try:
        return await ai.embed(db, texts)
    except ai.AiNotConfigured:
        return None, None
    except Exception:
        log.warning("memory embedding failed; storing without vectors", exc_info=True)
        return None, None


async def is_suppressed(
    db: AsyncSession, source_kind: str | None, source_id: uuid.UUID | None, entity_id: uuid.UUID, text: str,
    vector: list[float] | None, model: str | None,
) -> bool:
    rows = (
        await db.execute(
            select(MemSuppression)
            .options(undefer(MemSuppression.embedding))
            .where(
                MemSuppression.source_kind.is_not_distinct_from(source_kind),
                MemSuppression.source_id.is_not_distinct_from(source_id),
                MemSuppression.entity_id == entity_id,
            )
        )
    ).scalars()
    key = normalize(text)
    for s in rows:
        if normalize(s.text) == key:
            return True
        similar = vector is not None and s.embedding is not None and s.embedding_model == model
        if similar and cosine_distance(list(s.embedding), vector) <= SUPPRESS_DISTANCE:
            return True
    return False


def _hash(src: Source) -> str:
    """Text and scope: a KB document moved to another space is learned again, in its new scope."""
    kind, ref = src.scope
    return hashlib.sha256(f"{kind}|{ref}|{src.text}".encode()).hexdigest()


async def with_derived(db: AsyncSession, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """The given conclusions plus everything derived from them, transitively (reasoning chains)."""
    if not ids:
        return []
    rows = await db.execute(
        text(
            "WITH RECURSIVE d(id) AS (SELECT unnest(CAST(:ids AS uuid[]))"
            " UNION SELECT p.conclusion_id FROM mem_premises p JOIN d ON p.premise_id = d.id)"
            " SELECT id FROM d"
        ),
        {"ids": ids},
    )
    return list(rows.scalars())


async def clear_cards(db: AsyncSession, ids: list[uuid.UUID]) -> None:
    """Blanks every summary card built from these conclusions until the next dream rewrites it."""
    if ids:
        await db.execute(
            update(MemCard)
            .where(MemCard.conclusion_ids.has_any(array([str(i) for i in ids])))
            .values(summary_md="")
        )


async def retire(db: AsyncSession, ids: list[uuid.UUID], *, include_pinned: bool) -> None:
    """Supersedes these conclusions and everything derived from them, and clears the cards that used them."""
    every = await with_derived(db, ids)
    if not every:
        return
    stmt = update(MemConclusion).where(
        MemConclusion.id.in_(every), MemConclusion.status == ConclusionStatus.active
    )
    if not include_pinned:
        stmt = stmt.where(MemConclusion.pinned.is_(False))
    await db.execute(stmt.values(status=ConclusionStatus.superseded))
    await clear_cards(db, every)


@queue.register("mem.extract")
async def extract(db: AsyncSession, payload: dict) -> None:
    src = await load_source(db, payload["source_kind"], payload["source_id"])
    if src is None:
        return
    state = await db.get(MemSourceState, (src.kind, src.id))
    digest = _hash(src)
    if state is not None and state.text_hash == digest:
        return
    columns = scope_columns(src.scope)
    moved = (
        await db.execute(
            select(MemConclusion.id).where(
                MemConclusion.source_kind == src.kind,
                MemConclusion.source_id == src.id,
                MemConclusion.status == ConclusionStatus.active,
                or_(
                    MemConclusion.scope_kind != columns["scope_kind"],
                    MemConclusion.scope_team_id.is_distinct_from(columns["scope_team_id"]),
                    MemConclusion.scope_project_id.is_distinct_from(columns["scope_project_id"]),
                ),
            )
        )
    ).scalars().all()
    # the source now has other readers: nothing learned from it may stay where the old readers see it
    await retire(db, list(moved), include_pinned=True)
    messages = prompts.extraction_messages(src.candidates, src.kind, src.label, src.text)
    try:
        reply = await ai.complete(db, "extraction", messages)
    except ai.AiNotConfigured:
        return  # no state recorded: the source is read once extraction is configured
    out = ai.parse_json(reply, ExtractionOut)
    by_id = {f"E{i}": e for i, e in enumerate(src.candidates, start=1)}
    items: list[tuple] = []
    for item in out.conclusions:
        entity = by_id.get(item.entity.strip())
        text = " ".join(item.text.replace("\x00", "").split())
        if entity is None or not 1 <= len(text) <= TEXT_MAX:
            continue
        items.append((entity, text))
        if len(items) == MAX_CONCLUSIONS:
            break
    model, vectors = await embed_texts(db, [t for _, t in items])
    await db.execute(
        update(MemConclusion)
        .where(
            MemConclusion.source_kind == src.kind,
            MemConclusion.source_id == src.id,
            MemConclusion.kind == ConclusionKind.observed,
            MemConclusion.status == ConclusionStatus.active,
            MemConclusion.pinned.is_(False),
        )
        .values(status=ConclusionStatus.superseded)
    )
    for i, (entity, text) in enumerate(items):
        vector = vectors[i] if vectors else None
        if await is_suppressed(db, src.kind, src.id, entity.id, text, vector, model):
            continue
        db.add(
            MemConclusion(
                entity_id=entity.id, text=text, kind=ConclusionKind.observed, source_kind=src.kind,
                source_id=src.id, source_label=src.label, embedding=vector, embedding_model=model if vector else None,
                **scope_columns(src.scope),
            )
        )
    await db.execute(
        insert(MemSourceState)
        .values(source_kind=src.kind, source_id=src.id, text_hash=digest)
        .on_conflict_do_update(index_elements=["source_kind", "source_id"], set_={"text_hash": digest})
    )


@queue.register("mem.reconcile")
async def reconcile(db: AsyncSession, payload: dict) -> None:
    """Embeds active conclusions that lack a vector from the current embeddings model."""
    model = await ai.current_model(db, "embeddings")
    if model is None:
        return
    rows = (
        await db.execute(
            select(MemConclusion)
            .where(
                MemConclusion.status == ConclusionStatus.active,
                or_(MemConclusion.embedding_model.is_(None), MemConclusion.embedding_model != model),
            )
            .limit(RECONCILE_LIMIT)
        )
    ).scalars().all()
    if not rows:
        return
    used, vectors = await embed_texts(db, [r.text for r in rows])
    if vectors is None:
        return
    for row, vector in zip(rows, vectors, strict=True):
        row.embedding = vector
        row.embedding_model = used


# source kind -> its table, for finding sources that were deleted
SOURCE_TABLES = {
    "task": "tasks",
    "comment": "comments",
    "run": "agent_runs",
    "review": "workflow_step_reviews",
    "kb_document": "kb_documents",
}
FORGET_SECONDS = 1800
BACKFILL_PAGE = 500
BACKFILL_KINDS = ("task", "comment", "kb_document", "run", "review")


@queue.register("mem.forget")
async def forget_missing(db: AsyncSession, payload: dict) -> None:
    """Forgets what was learned from deleted sources: their unpinned observed conclusions (and what was derived
    from them) are superseded and the cards built on them cleared. Human corrections and pinned facts stay."""
    for kind, table in SOURCE_TABLES.items():
        missing = text(f"NOT EXISTS (SELECT 1 FROM {table} t WHERE t.id = mem_conclusions.source_id)")
        ids = (
            await db.execute(
                select(MemConclusion.id).where(
                    MemConclusion.source_kind == kind,
                    MemConclusion.kind == ConclusionKind.observed,
                    MemConclusion.status == ConclusionStatus.active,
                    MemConclusion.pinned.is_(False),
                    missing,
                )
            )
        ).scalars().all()
        await retire(db, list(ids), include_pinned=False)
        await db.execute(
            text(
                f"DELETE FROM mem_source_states s WHERE s.source_kind = :kind"
                f" AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.id = s.source_id)"
            ),
            {"kind": kind},
        )


@queue.register("mem.backfill")
async def backfill(db: AsyncSession, payload: dict) -> None:
    """Queues extraction for sources never read (written before extraction was configured), page by page."""
    kind = payload.get("kind", BACKFILL_KINDS[0])
    after = payload.get("after")
    table = SOURCE_TABLES[kind]
    finished = " AND t.status NOT IN ('queued', 'running')" if kind == "run" else ""
    rows = await db.execute(
        text(
            f"SELECT t.id FROM {table} t WHERE NOT EXISTS (SELECT 1 FROM mem_source_states s"
            f" WHERE s.source_kind = :kind AND s.source_id = t.id){finished}"
            f"{' AND t.id > CAST(:after AS uuid)' if after else ''} ORDER BY t.id LIMIT :limit"
        ),
        {"kind": kind, "limit": BACKFILL_PAGE, **({"after": after} if after else {})},
    )
    ids = list(rows.scalars())
    for sid in ids:
        await queue_extract(db, kind, sid)
    if len(ids) == BACKFILL_PAGE:
        nxt = {"kind": kind, "after": str(ids[-1])}
    elif kind != BACKFILL_KINDS[-1]:
        nxt = {"kind": BACKFILL_KINDS[BACKFILL_KINDS.index(kind) + 1]}
    else:
        return
    await queue.enqueue(db, "mem.backfill", nxt, dedupe_key="mem.backfill")


queue.register_periodic("mem.reconcile", RECONCILE_SECONDS)
queue.register_periodic("mem.forget", FORGET_SECONDS)
if "mem.reconcile" not in ai.REINDEX_JOBS:
    ai.REINDEX_JOBS.append("mem.reconcile")
