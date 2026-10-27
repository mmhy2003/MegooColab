"""Global search for people (Plan 9). The browser only talks to these endpoints; Meilisearch stays internal."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.audit import service as audit
from app.auth.deps import AdminUser, AuthedUser
from app.core.db import DbSession
from app.jobs import queue
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.search import client, service
from app.search.schemas import GlobalSearchOut, QuickOut, SearchAdminOut

router = APIRouter(tags=["search"])

Q = Annotated[str, Query(min_length=1, max_length=service.MAX_Q)]
Many = Annotated[list[str], Query()]


def _unavailable() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "search_unavailable")


@router.get("/api/search/quick")
async def quick_search(user: AuthedUser, db: DbSession, q: Q) -> QuickOut:
    try:
        return await service.quick(db, user, q)
    except client.SearchUnavailable:
        raise _unavailable() from None


@router.get("/api/search")
async def search(
    user: AuthedUser,
    db: DbSession,
    q: Q,
    kind: Many = [],  # noqa: B006 - FastAPI copies query defaults
    project: Many = [],  # noqa: B006
    status_: Annotated[list[str], Query(alias="status")] = [],  # noqa: B006
    assignee: Many = [],  # noqa: B006
    type_: Annotated[list[str], Query(alias="type")] = [],  # noqa: B006
    label: Many = [],  # noqa: B006
    updated: str | None = None,
    sort: Annotated[str, Query(pattern="^(relevance|newest)$")] = "relevance",
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    meaning: bool = False,
) -> GlobalSearchOut:
    filters = service.parse_filters(kind, project, status_, assignee, type_, label, updated)
    try:
        return await service.full(db, user, q, filters, sort=sort, offset=offset, meaning=meaning)
    except client.SearchUnavailable:
        raise _unavailable() from None


@router.get("/api/admin/search")
async def search_status(admin: AdminUser, db: DbSession) -> SearchAdminOut:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    available = await client.health()
    documents = None
    if available:
        try:
            documents = await client.document_count()
        except client.SearchUnavailable:
            available = False
    return SearchAdminOut(available=available, documents=documents,
                          last_rebuild_at=org.search_rebuilt_at if org else None)


@router.post("/api/admin/search/rebuild", status_code=status.HTTP_202_ACCEPTED)
async def rebuild_search(admin: AdminUser, db: DbSession) -> dict:
    await queue.enqueue(db, "search.rebuild", {}, dedupe_key="search.rebuild")
    await audit.record(db, "search.rebuild", actor_id=admin.id)
    return {"queued": True}
