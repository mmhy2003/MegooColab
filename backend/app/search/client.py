"""The Meilisearch client (Plan 9): one index for everything people can search.

The official client is synchronous, so every call runs in a thread (`call`). Any failure to reach or use
Meilisearch becomes `SearchUnavailable`: search answers 503, and saving anything never depends on it.
"""

import asyncio
from collections.abc import Callable
from typing import Any

import meilisearch
from meilisearch.errors import (
    MeilisearchApiError,
    MeilisearchCommunicationError,
    MeilisearchTimeoutError,
)

from app.core.config import get_settings

TIMEOUT_SECONDS = 5
TASK_TIMEOUT_MS = 30_000

SEARCHABLE = ["key", "title", "body", "comments"]
FILTERABLE = ["kind", "readers", "project_id", "status", "assignee", "type", "labels", "updated_at"]
SORTABLE = ["updated_at"]
INDEX_SETTINGS: dict[str, Any] = {
    "searchableAttributes": SEARCHABLE,
    "filterableAttributes": FILTERABLE,
    "sortableAttributes": SORTABLE,
    # keys (PAY-42) match exactly; everything else keeps the defaults: 1 typo from 5 letters, 2 from 9
    "typoTolerance": {"disableOnAttributes": ["key"]},
    "faceting": {"maxValuesPerFacet": 100},
}


class SearchUnavailable(Exception):
    """Meilisearch could not be reached or refused the request."""


_clients: dict[tuple[str, str], meilisearch.Client] = {}


def client() -> meilisearch.Client:
    settings = get_settings()
    key = (settings.meili_url, settings.meili_master_key)
    if key not in _clients:
        _clients[key] = meilisearch.Client(settings.meili_url, settings.meili_master_key or None, timeout=TIMEOUT_SECONDS)
    return _clients[key]


def index():
    return client().index(get_settings().meili_index)


async def call[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a client call in a thread; every Meilisearch failure becomes SearchUnavailable."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), TIMEOUT_SECONDS * 2)
    except (MeilisearchCommunicationError, MeilisearchApiError, MeilisearchTimeoutError, TimeoutError, OSError) as e:
        raise SearchUnavailable(type(e).__name__) from None


def _wait(task) -> None:
    client().wait_for_task(task.task_uid, timeout_in_ms=TASK_TIMEOUT_MS)


async def ensure_index() -> None:
    """Create the index if it is missing and apply the settings. Idempotent."""
    name = get_settings().meili_index

    def run() -> None:
        try:
            client().get_index(name)
        except MeilisearchApiError as e:
            if e.code != "index_not_found":
                raise
            _wait(client().create_index(name, {"primaryKey": "id"}))
        _wait(client().index(name).update_settings(INDEX_SETTINGS))

    await call(run)


async def document_count() -> int:
    stats = await call(lambda: index().get_stats())
    return int(stats.number_of_documents)


async def health_or_raise() -> None:
    await call(lambda: client().health())


async def health() -> bool:
    try:
        await health_or_raise()
    except SearchUnavailable:
        return False
    return True
