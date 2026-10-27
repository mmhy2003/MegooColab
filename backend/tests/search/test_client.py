"""Meilisearch client and index settings (Plan 9 Task 1)."""

import time

import pytest

from app.core.config import get_settings
from app.search import client


async def _settings(name: str) -> dict:
    return await client.call(lambda: client.client().index(name).get_settings())


async def test_ensure_index_applies_settings(meili_index):
    s = await _settings(meili_index)
    assert s["searchableAttributes"] == ["key", "title", "body", "comments"]
    assert sorted(s["filterableAttributes"]) == sorted(
        ["kind", "readers", "project_id", "status", "assignee", "type", "labels", "updated_at"])
    assert s["sortableAttributes"] == ["updated_at"]
    assert s["typoTolerance"]["disableOnAttributes"] == ["key"]
    assert s["faceting"]["maxValuesPerFacet"] == 100


async def test_ensure_index_is_idempotent(meili_index):
    await client.ensure_index()
    s = await _settings(meili_index)
    assert s["searchableAttributes"] == ["key", "title", "body", "comments"]
    indexes = await client.call(lambda: client.client().get_indexes({"limit": 1000}))
    assert [i.uid for i in indexes["results"]].count(meili_index) == 1


async def test_unreachable_meilisearch_raises_search_unavailable():
    settings = get_settings()
    before = settings.meili_url
    settings.meili_url = "http://127.0.0.1:9"
    try:
        start = time.monotonic()
        with pytest.raises(client.SearchUnavailable):
            await client.health_or_raise()
        assert time.monotonic() - start < 10
        assert await client.health() is False
    finally:
        settings.meili_url = before


async def test_health_and_document_count(meili_index):
    assert await client.health() is True
    assert await client.document_count() == 0
