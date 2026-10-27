"""Search index jobs (Plan 9). Each is idempotent: it reads the database, the source of truth, and writes the
result to Meilisearch. A `SearchUnavailable` fails the job, and the queue retries it with backoff."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserStatus
from app.jobs import queue
from app.kb.models import KbDocument
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.projects.models import Project
from app.search import client, documents
from app.search.capture import SKIP
from app.tasks.models import Task

BATCH = 500
ENSURE_SECONDS = 60


@queue.register("search.sync")
async def sync(db: AsyncSession, payload: dict) -> None:
    db.info[SKIP] = True
    kind, id = payload["kind"], uuid.UUID(payload["id"])
    await client.ensure_once()
    doc = await documents.build(db, kind, id)
    if doc is None:
        await client.call(lambda: client.wait(client.index().delete_document(documents.doc_id(kind, id))))
    else:
        await client.call(lambda: client.wait(client.index().add_documents([doc], primary_key="id")))


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@queue.register("search.purge")
async def purge(db: AsyncSession, payload: dict) -> None:
    field = payload["field"]
    if field not in ("project_id", "readers"):
        raise ValueError(f"unknown purge field {field!r}")
    flt = f"{field} = {_quoted(str(payload['value']))}"
    await client.ensure_once()
    await client.call(lambda: client.wait(client.index().delete_documents(filter=flt)))


async def _indexed_ids() -> set[str]:
    def run() -> set[str]:
        ids: set[str] = set()
        offset = 0
        while True:
            page = client.index().get_documents({"fields": ["id"], "limit": 1000, "offset": offset})
            ids.update(getattr(d, "id", None) or d["id"] for d in page.results)
            if len(page.results) < 1000:
                return ids
            offset += 1000

    return await client.call(run)


@queue.register("search.rebuild")
async def rebuild(db: AsyncSession, payload: dict) -> None:
    """Index every item from the database, then remove documents whose items are gone."""
    db.info[SKIP] = True
    await client.ensure_index()
    wanted: set[str] = set()
    batch: list[dict] = []

    async def flush() -> None:
        if batch:
            docs = list(batch)
            await client.call(lambda: client.wait(client.index().add_documents(docs, primary_key="id")))
            batch.clear()

    for kind in documents.KINDS:
        async for id in documents.ids_of(db, kind):
            doc = await documents.build(db, kind, id)
            if doc is None:
                continue
            wanted.add(doc["id"])
            batch.append(doc)
            if len(batch) >= BATCH:
                await flush()
    await flush()
    stale = sorted(await _indexed_ids() - wanted)

    def prune() -> None:
        last = None
        for id in stale:  # rare (items deleted while Meilisearch was away); tasks run in order
            last = client.index().delete_document(id)
        if last is not None:
            client.wait(last)

    await client.call(prune)
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    if org is not None:
        org.search_rebuilt_at = datetime.now(UTC)


async def _has_rows(db: AsyncSession) -> bool:
    for stmt in (
        select(func.count()).select_from(Task),
        select(func.count()).select_from(KbDocument),
        select(func.count()).select_from(Project),
        select(func.count()).select_from(User).where(User.status == UserStatus.active),
    ):
        if await db.scalar(stmt):
            return True
    return False


@queue.register("search.ensure")
async def ensure(db: AsyncSession, payload: dict) -> None:
    """Apply the index settings, and rebuild from the database when the index may be missing data: it was just
    created or had lost its settings, it is empty, or this install has never been rebuilt (an upgrade to search,
    where a login or an edit may already have put a few documents in)."""
    fresh = await client.ensure_index()
    if not await _has_rows(db):
        return
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    never = org is not None and org.search_rebuilt_at is None
    if fresh or never or await client.document_count() == 0:
        await queue.enqueue(db, "search.rebuild", {}, dedupe_key="search.rebuild")


queue.register_periodic("search.ensure", ENSURE_SECONDS)
