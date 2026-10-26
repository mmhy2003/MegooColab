"""Regression tests for the Plan 4 final review findings."""

import asyncio
import time

import litellm
import pytest
from sqlalchemy import select, update

from app.auth.models import Role
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.jobs import queue
from app.jobs.models import Job, JobStatus
from app.kb import access, search, service
from app.kb import context as kb_context
from app.kb.models import KbChunk
from app.workflow import context
from app.workflow.models import RunRole
from tests.factories import login, make_user
from tests.kb.test_context import _doc, _world
from tests.kb.test_search import _drain
from tests.kb.test_search import _world as _search_world

# -- 1. a diff never blocks the server for long ------------------------------------------------------


def test_diff_of_huge_repetitive_bodies_is_fast_and_correct():
    a = "\n".join(["", "-", "x"] * 60_000)[:500_000]
    b_lines = a.split("\n")
    b_lines[1000] = "changed"
    b_lines[-1000] = "also changed"
    b = "\n".join(b_lines)
    start = time.monotonic()
    ops = service.diff(a, b)
    assert time.monotonic() - start < 3
    changed = [o for o in ops if o["op"] not in ("equal", "collapsed")]
    assert changed[0]["b_lines"][0] == "changed" and changed[-1]["b_lines"][-1] == "also changed"
    unrelated = "\n".join(["y", "-", ""] * 60_000)[:500_000]
    start = time.monotonic()
    ops = service.diff(a, unrelated)
    assert time.monotonic() - start < 3
    assert {o["op"] for o in ops} <= {"replace", "equal", "collapsed", "insert", "delete"}


async def test_diff_endpoint_does_not_block_the_event_loop(client, db, monkeypatch):
    w = await _search_world(client, db)
    r = await client.post(f"/api/kb/spaces/{w['org'].id}/documents", json={"title": "T", "body_md": "a"})
    doc = r.json()
    await client.put(f"/api/kb/documents/{doc['id']}", json={"base_revision": 1, "body_md": "b"})

    def slow(a, b):
        time.sleep(0.5)
        return []

    monkeypatch.setattr(service, "diff", slow)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    t = asyncio.create_task(ticker())
    r = await client.get(f"/api/kb/documents/{doc['id']}/revisions/1/diff/2")
    t.cancel()
    assert r.status_code == 200
    assert ticks >= 5  # the loop kept running while the diff was computed


# -- 2. a failing job with a newer queued copy --------------------------------------------------------


async def test_fail_with_newer_queued_copy_records_error(db):
    await queue.enqueue(db, "t.x", {}, dedupe_key="k")
    await db.commit()
    running = await queue.claim(db, {"t.x"})
    await db.commit()
    newer = await queue.enqueue(db, "t.x", {}, dedupe_key="k")
    await db.commit()
    await queue.fail(db, running, "provider down")
    await db.commit()
    await db.refresh(running)
    assert running.status == JobStatus.failed and "provider down" in running.last_error
    await db.refresh(newer)
    assert newer.status == JobStatus.queued


# -- 3. documents that failed to embed are embedded again ---------------------------------------------


async def test_reconcile_embeds_documents_missing_current_vectors(client, db):
    w = await _search_world(client, db)
    a = (await client.post(f"/api/kb/spaces/{w['org'].id}/documents", json={"title": "A", "body_md": "a"})).json()
    b = (await client.post(f"/api/kb/spaces/{w['org'].id}/documents", json={"title": "B", "body_md": "b"})).json()
    await _drain()
    await db.execute(update(KbChunk).where(KbChunk.document_id == a["id"]).values(embedding_model=None, embedding=None))
    await db.commit()
    async with SessionLocal() as s:
        await search.reconcile(s, {})
        await s.commit()
    queued = (await db.execute(select(Job).where(Job.status == JobStatus.queued))).scalars().all()
    assert [j.payload["document_id"] for j in queued] == [a["id"]]
    assert b["id"] not in [j.payload["document_id"] for j in queued]


async def test_provider_change_queues_reconcile(client, db):
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    pid = (await client.post("/api/admin/ai/providers", json={"name": "P", "kind": "openai", "api_key": "bad"})).json()["id"]
    await client.put("/api/admin/ai/jobs/embeddings", json={"provider_id": pid, "model": "m"})
    await db.execute(update(Job).values(status=JobStatus.done))
    await db.commit()
    await client.patch(f"/api/admin/ai/providers/{pid}", json={"api_key": "good"})
    kinds = [j.kind for j in (await db.execute(select(Job).where(Job.status == JobStatus.queued))).scalars()]
    assert kinds == ["kb.reconcile"]
    # saving the same model again is also a retry
    await db.execute(update(Job).values(status=JobStatus.done))
    await db.commit()
    await client.put("/api/admin/ai/jobs/embeddings", json={"provider_id": pid, "model": "m"})
    kinds = [j.kind for j in (await db.execute(select(Job).where(Job.status == JobStatus.queued))).scalars()]
    assert kinds == ["kb.reconcile"]


def test_reconcile_is_periodic():
    assert queue.PERIODIC.get("kb.reconcile") == search.RECONCILE_SECONDS


async def test_worker_enqueues_due_periodic_jobs(db, monkeypatch):
    monkeypatch.setattr(queue, "PERIODIC", {"t.tick": 3600})
    from app.jobs import worker

    last: dict[str, float] = {}
    await worker.enqueue_periodic(last, now=1000.0)
    await worker.enqueue_periodic(last, now=1001.0)  # not due again yet
    jobs = (await db.execute(select(Job))).scalars().all()
    assert [j.kind for j in jobs] == ["t.tick"]


# -- 4. relevance -------------------------------------------------------------------------------------


async def test_unrelated_documents_stay_out_of_prompts_and_search(client, db):
    task, manager, org, _ = await _world(client, db, title="Fix the login button colour",
                                          description="The button is the wrong shade of blue.")
    await _doc(client, db, org.id, "Holiday calendar", "Offices close on the first Monday of the month.")
    assert await kb_context.kb_context(db, task, RunRole.implement) is None
    out = await search.search(db, manager, "zebra")
    assert out["results"] == []
    await _doc(client, db, org.id, "Login button", "The login button colour comes from the theme.")
    section = await kb_context.kb_context(db, task, RunRole.implement)
    assert "Login button" in section and "Holiday" not in section


async def test_kb_section_is_trimmed_before_the_thread(client, db, monkeypatch):
    task, _, org, _ = await _world(client, db)
    await _doc(client, db, org.id, "Webhook secrets", "Rotate webhook secrets. " * 300)
    kb_context.register()
    monkeypatch.setattr(context, "MAX_PROMPT_CHARS", 9_000)
    task.description_md = "Webhook secrets expire. " * 200
    await db.commit()
    prompt, _ = await context.build_prompt(db, task, RunRole.brainstorm)
    assert "## Knowledge Base" not in prompt
    assert "Webhook secrets expire." in prompt


# -- 5. a slow or failing provider ----------------------------------------------------------------------


async def test_query_embeds_use_a_short_timeout(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_fake", False)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    pid = (await client.post("/api/admin/ai/providers", json={"name": "P", "kind": "openai", "api_key": "k"})).json()["id"]
    await client.put("/api/admin/ai/jobs/embeddings", json={"provider_id": pid, "model": "m"})
    seen = []

    async def fake(**kw):
        seen.append(kw["timeout"])
        raise TimeoutError

    monkeypatch.setattr(litellm, "aembedding", fake)
    await access.ensure_spaces(db)
    await db.commit()
    out = await search.search(db, admin, "anything")
    assert out["semantic"] is False and seen == [search.QUERY_TIMEOUT_SECONDS]
    assert search.QUERY_TIMEOUT_SECONDS <= 5


async def test_failing_context_provider_does_not_break_the_prompt(client, db, monkeypatch):
    task, _, _, _ = await _world(client, db)

    async def boom(db_, task_, role_):
        raise RuntimeError("provider bug")

    monkeypatch.setattr(context, "context_providers", [boom])
    prompt, _ = await context.build_prompt(db, task, RunRole.brainstorm)
    assert "## Task PAY-" in prompt


@pytest.fixture(autouse=True)
def _restore_providers():
    saved = list(context.context_providers)
    yield
    context.context_providers[:] = saved
