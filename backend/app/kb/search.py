"""Knowledge Base search: full-text (tsvector) and semantic (pgvector) results fused by reciprocal rank.

Documents are split into overlapping chunks that a background job embeds with the configured model.
Only chunks embedded by the current model are compared; after a model change every document is re-embedded.
"""

import logging
import re
import uuid

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import client as ai
from app.auth.models import User
from app.jobs import queue
from app.kb import access, service
from app.kb.models import KbChunk, KbDocument, KbSpace

log = logging.getLogger(__name__)

CHUNK_SIZE = 3000
CHUNK_OVERLAP = 300
CHUNK_LIMIT = 2000
LIST_LIMIT = 50
RRF_K = 60
SNIPPET = 300
REEMBED_PAGE = 500


def chunk(body: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP, limit: int = CHUNK_LIMIT) -> list[str]:
    """Splits on a blank line in the second half of a window when there is one, else at `size`."""
    out: list[str] = []
    start = 0
    while start < len(body) and len(out) < limit:
        end = min(start + size, len(body))
        if end < len(body):
            cut = body.rfind("\n\n", start + size // 2, end)
            if cut != -1:
                end = cut + 2
        out.append(body[start:end])
        if end >= len(body):
            break
        start = max(end - overlap, start + 1)
    return out


# -- background jobs ---------------------------------------------------------------------------------


@queue.register("kb.embed")
async def embed_document(db: AsyncSession, payload: dict) -> None:
    doc_id = uuid.UUID(payload["document_id"])
    # one embedder per document at a time; saves are not blocked
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"kb.embed:{doc_id}"})
    doc = await db.get(KbDocument, doc_id, populate_existing=True)
    if doc is None:
        return
    model = await ai.current_model(db, "embeddings")
    existing = (await db.execute(select(KbChunk.revision, KbChunk.embedding_model).where(KbChunk.document_id == doc_id))).all()
    if existing and all(r == doc.latest_revision and m == model for r, m in existing):
        return
    pieces = chunk(doc.body_md) or [""]
    vectors: list[list[float]] | None = None
    used: str | None = None
    if model is not None:
        try:
            used, vectors = await ai.embed(db, [f"{doc.title}\n\n{p}" for p in pieces])
        except ai.AiNotConfigured:
            vectors = None
    await db.execute(delete(KbChunk).where(KbChunk.document_id == doc_id))
    db.add_all(
        KbChunk(
            document_id=doc_id, revision=doc.latest_revision, ordinal=i, text=p,
            embedding=vectors[i] if vectors else None, embedding_model=used if vectors else None,
        )
        for i, p in enumerate(pieces)
    )


@queue.register("kb.reembed_all")
async def reembed_all(db: AsyncSession, payload: dict) -> None:
    after = uuid.UUID(payload["after"]) if payload.get("after") else None
    stmt = select(KbDocument.id).order_by(KbDocument.id).limit(REEMBED_PAGE)
    if after is not None:
        stmt = stmt.where(KbDocument.id > after)
    ids = list((await db.execute(stmt)).scalars())
    for doc_id in ids:
        await service.enqueue_embed(db, doc_id)
    if len(ids) == REEMBED_PAGE:
        await queue.enqueue(db, "kb.reembed_all", {"after": str(ids[-1])})



# -- search ------------------------------------------------------------------------------------------


def _terms(q: str) -> list[str]:
    return [t.lower() for t in re.findall(r"\w+", q)]


def snippet(body: str, terms: list[str], fallback: str | None = None) -> str:
    lower = body.lower()
    hits = [i for i in (lower.find(t) for t in terms) if i != -1]
    if hits:
        start = max(0, min(hits) - 100)
        window = body[start : start + SNIPPET]
    else:
        window = (fallback if fallback is not None else body)[:SNIPPET]
    return re.sub(r"\s+", " ", window).strip()[:SNIPPET]


async def _fts(db: AsyncSession, q: str, scope: set[uuid.UUID]) -> list[uuid.UUID]:
    tsq = func.websearch_to_tsquery(text("'simple'::regconfig"), q)
    rows = await db.execute(
        select(KbDocument.id)
        .where(KbDocument.space_id.in_(scope), KbDocument.search_tsv.op("@@")(tsq))
        .order_by(func.ts_rank_cd(KbDocument.search_tsv, tsq).desc(), KbDocument.title)
        .limit(LIST_LIMIT)
    )
    return list(rows.scalars())


async def _semantic(db: AsyncSession, q: str, scope: set[uuid.UUID]) -> tuple[bool, list[uuid.UUID], dict]:
    model = await ai.current_model(db, "embeddings")
    if model is None:
        return False, [], {}
    try:
        used, (qvec,) = await ai.embed(db, [q])
    except ai.AiNotConfigured:
        return False, [], {}
    except Exception:
        log.warning("semantic search unavailable", exc_info=True)
        return False, [], {}
    rows = await db.execute(
        select(KbChunk.document_id, KbChunk.text)
        .join(KbDocument, KbDocument.id == KbChunk.document_id)
        .where(
            KbDocument.space_id.in_(scope),
            KbChunk.embedding_model == used,
            KbChunk.embedding.is_not(None),
        )
        .order_by(KbChunk.embedding.cosine_distance(qvec))
        .limit(LIST_LIMIT * 4)
    )
    order: list[uuid.UUID] = []
    best: dict[uuid.UUID, str] = {}
    for doc_id, chunk_text in rows:
        if doc_id not in best:
            best[doc_id] = chunk_text
            order.append(doc_id)
    return True, order[:LIST_LIMIT], best


async def search(
    db: AsyncSession,
    user: User,
    query: str,
    *,
    space_ids: set[uuid.UUID] | None = None,
    limit: int = 20,
    match_any: bool = False,
) -> dict:
    """Hybrid search over the spaces the user can read: {semantic, results: [...]}. Full-text needs every word
    unless `match_any` (used for prompt context, where the query is a whole task description). Each result also
    carries `excerpt`, its best chunk, for callers that show more than the snippet."""
    scope = await access.readable_space_ids(db, user)
    if space_ids is not None:
        scope &= space_ids
    terms = _terms(query)
    if not scope or not terms:
        return {"semantic": await ai.current_model(db, "embeddings") is not None, "results": []}
    fts = await _fts(db, " or ".join(dict.fromkeys(terms[:50])) if match_any else query, scope)
    semantic, sem, best = await _semantic(db, query, scope)
    scores: dict[uuid.UUID, float] = {}
    for ranked in (fts, sem):
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (RRF_K + rank)
    if not scores:
        return {"semantic": semantic, "results": []}
    docs = {d.id: d for d in (await db.execute(select(KbDocument).where(KbDocument.id.in_(scores)))).scalars()}
    ordered = sorted(scores, key=lambda i: (-scores[i], docs[i].title.lower()))[:limit]
    results = []
    for doc_id in ordered:
        doc = docs[doc_id]
        space = await db.get(KbSpace, doc.space_id)
        results.append(
            {
                "document_id": doc.id,
                "space": await service.space_ref(db, space),
                "title": doc.title,
                "path": await service.folder_path(db, doc.folder_id),
                "snippet": snippet(doc.body_md, terms, best.get(doc_id)),
                "score": round(scores[doc_id], 6),
                "excerpt": best.get(doc_id) or doc.body_md[:CHUNK_SIZE],
            }
        )
    return {"semantic": semantic, "results": results}
