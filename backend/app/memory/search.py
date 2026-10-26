"""Scoped hybrid retrieval over conclusions (MEM-9): full-text and vectors fused by reciprocal rank."""

import logging
import uuid

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import client as ai
from app.auth.models import User
from app.kb.search import (
    QUERY_TIMEOUT_SECONDS,
    RRF_K,
    SEMANTIC_MAX_DISTANCE,
    STOPWORDS,
    _terms,
)
from app.memory.access import readable_scopes
from app.memory.models import ConclusionStatus, MemConclusion, ScopeKind
from app.projects.models import ProjectTeam

log = logging.getLogger(__name__)

LIST_LIMIT = 50
PINNED_BONUS = 0.01


async def _project_filter(db: AsyncSession, project_id: uuid.UUID):
    """The scopes relevant to one project: the project, its teams, the org."""
    teams = set((await db.execute(select(ProjectTeam.team_id).where(ProjectTeam.project_id == project_id))).scalars())
    return or_(
        MemConclusion.scope_kind == ScopeKind.org,
        and_(MemConclusion.scope_kind == ScopeKind.team, MemConclusion.scope_team_id.in_(teams)),
        and_(MemConclusion.scope_kind == ScopeKind.project, MemConclusion.scope_project_id == project_id),
    )


async def search_conclusions(
    db: AsyncSession,
    user: User,
    query: str,
    *,
    entity_ids: set[uuid.UUID] | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = 20,
    match_any: bool = True,
) -> list[MemConclusion]:
    terms = _terms(query)
    words = [t for t in dict.fromkeys(terms) if len(t) > 2 and t not in STOPWORDS][:50]
    if not words:
        return []
    scopes = await readable_scopes(db, user)
    filters = [MemConclusion.status == ConclusionStatus.active, scopes.clause(MemConclusion)]
    if entity_ids is not None:
        filters.append(MemConclusion.entity_id.in_(entity_ids))
    if project_id is not None:
        filters.append(await _project_filter(db, project_id))

    tsq = func.websearch_to_tsquery(text("'simple'::regconfig"), " or ".join(words) if match_any else query)
    fts = list(
        (
            await db.execute(
                select(MemConclusion.id)
                .where(*filters, MemConclusion.search_tsv.op("@@")(tsq))
                .order_by(func.ts_rank_cd(MemConclusion.search_tsv, tsq).desc())
                .limit(LIST_LIMIT)
            )
        ).scalars()
    )
    sem: list[uuid.UUID] = []
    if await ai.current_model(db, "embeddings") is not None:
        try:
            used, (qvec,) = await ai.embed(db, [query], timeout=QUERY_TIMEOUT_SECONDS)
            sem = list(
                (
                    await db.execute(
                        select(MemConclusion.id)
                        .where(
                            *filters,
                            MemConclusion.embedding_model == used,
                            MemConclusion.embedding.is_not(None),
                            MemConclusion.embedding.cosine_distance(qvec) <= SEMANTIC_MAX_DISTANCE,
                        )
                        .order_by(MemConclusion.embedding.cosine_distance(qvec))
                        .limit(LIST_LIMIT)
                    )
                ).scalars()
            )
        except ai.AiNotConfigured:
            pass
        except Exception:
            log.warning("memory semantic search unavailable", exc_info=True)
    scores: dict[uuid.UUID, float] = {}
    for ranked in (fts, sem):
        for rank, cid in enumerate(ranked, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    if not scores:
        return []
    rows = {r.id: r for r in (await db.execute(select(MemConclusion).where(MemConclusion.id.in_(scores)))).scalars()}
    for cid, row in rows.items():
        if row.pinned:
            scores[cid] += PINNED_BONUS
    ordered = sorted(rows, key=lambda cid: (-scores[cid], rows[cid].created_at), reverse=False)
    return [rows[cid] for cid in ordered[:limit]]
