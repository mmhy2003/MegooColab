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
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.ai import client as ai
from app.jobs import queue
from app.memory import prompts
from app.memory.models import (
    ConclusionKind,
    ConclusionStatus,
    MemConclusion,
    MemSourceState,
    MemSuppression,
    ScopeKind,
)
from app.memory.sources import Source, load_source

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
    return hashlib.sha256(src.text.encode()).hexdigest()


@queue.register("mem.extract")
async def extract(db: AsyncSession, payload: dict) -> None:
    src = await load_source(db, payload["source_kind"], payload["source_id"])
    if src is None:
        return
    state = await db.get(MemSourceState, (src.kind, src.id))
    digest = _hash(src)
    if state is not None and state.text_hash == digest:
        return
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


queue.register_periodic("mem.reconcile", RECONCILE_SECONDS)
if "mem.reconcile" not in ai.REINDEX_JOBS:
    ai.REINDEX_JOBS.append("mem.reconcile")
