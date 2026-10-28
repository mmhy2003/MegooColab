"""System (admins): runners, background jobs, search, AI, memory and rate limits."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.ai.models import AiProvider, AiUsage
from app.audit.models import AuditLog
from app.dashboard.system import reset_search_cache
from app.jobs.models import Job
from app.memory.models import MemDreamRun
from app.runner.registry import registry
from app.search import client as search_client
from tests.dashboard.conftest import dash
from tests.factories import login


async def test_system_lines_for_admins(client, db, world, monkeypatch):
    now = datetime.now(UTC)
    await login(client, world.admin)
    await db.execute(delete(Job))  # setting up the world and signing in queue search jobs
    db.add_all([
        Job(kind="x", run_after=now - timedelta(minutes=6)), Job(kind="x", run_after=now),
        Job(kind="x", run_after=now + timedelta(hours=1)),
        AuditLog(action="rate_limit.blocked", data={}), AuditLog(action="rate_limit.blocked", data={}),
        AuditLog(action="rate_limit.blocked", data={}, created_at=now - timedelta(days=2)),
        AiProvider(name="p", kind="openai"),
        AiUsage(job="embeddings", model="m", ok=True), AiUsage(job="embeddings", model="m", ok=False),
        MemDreamRun(trigger="schedule", status="failed", finished_at=now - timedelta(hours=1)),
    ])
    await db.commit()
    monkeypatch.setattr(registry, "connected_count", lambda: 2)
    calls = []

    async def health():
        calls.append(1)
        return True

    async def count():
        return 42

    monkeypatch.setattr(search_client, "health", health)
    monkeypatch.setattr(search_client, "document_count", count)
    reset_search_cache()
    s = (await dash(client, "all"))["system"]
    assert s["runners"] == 2 and s["agents_exist"] is True
    assert s["jobs_waiting"] == 2 and s["oldest_job_seconds"] >= 360
    assert (s["search_available"], s["search_documents"]) == (True, 42)
    assert (s["ai_configured"], s["ai_jobs_today"], s["ai_failed_today"]) == (True, 2, 1)
    assert s["memory_last_failed"] is True and s["memory_last_at"] is not None and s["rate_limits_24h"] == 2
    await dash(client, "all")
    assert len(calls) == 1  # cached for 60 s


async def test_search_down_is_reported_not_raised(client, db, world, monkeypatch):
    async def health():
        return False

    monkeypatch.setattr(search_client, "health", health)
    reset_search_cache()
    await login(client, world.admin)
    await db.execute(delete(Job))
    await db.commit()
    s = (await dash(client, "all"))["system"]
    assert (s["search_available"], s["search_documents"]) == (False, None)
    assert s["memory_last_at"] is None and s["memory_last_failed"] is False and s["oldest_job_seconds"] is None
