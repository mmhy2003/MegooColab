"""The Knowledge Base and Memory sections are added after the commit, before the run is sent (MC-215)."""

import json
import logging
import uuid

from sqlalchemy import update

from app.agent_runs import late_context
from app.agent_runs.models import AgentRun, RunStatus
from app.agent_runs.service import _claim_next, dispatch_pending
from app.core.db import SessionLocal
from app.runner.registry import registry
from app.workflow import context
from tests.agent_runs.test_dispatch import _fake_conn, _FakeSocket, _offline_runs

PROMPT = "BASE\n\n## Answer\nyes"
KB, MEM = "## Knowledge Base\nkb", "## Memory\nmem"


async def _kb(db, task, role):
    return KB


async def _mem(db, task, role):
    return MEM


async def _marked(client, db, prompt=PROMPT, at=4, **fields):
    """A queued plan run whose prompt waits for its late sections at `at`."""
    me, agent, runs = await _offline_runs(client, db)
    run_id = uuid.UUID(runs[0]["id"])
    await db.execute(update(AgentRun).where(AgentRun.id == run_id).values(
        workflow_role="plan", stage="plan", prompt=prompt, context_at=at, **fields))
    await db.commit()
    return me, agent, run_id


async def _run(run_id) -> AgentRun:
    async with SessionLocal() as s:
        return await s.get(AgentRun, run_id)


async def _set(run_id, **fields):
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run_id).values(**fields))
        await s.commit()


async def test_sections_land_at_the_mark_before_the_resume_note(client, db, monkeypatch):
    monkeypatch.setattr(context, "late_providers", [_kb, _mem])
    me, _, run_id = await _marked(client, db)
    await late_context.fill_pending(me.id)
    run = await _run(run_id)
    assert run.prompt == "BASE\n\n" + KB + "\n\n" + MEM + "\n\n## Answer\nyes"
    assert run.context_at is None


async def test_sections_that_do_not_fit_are_left_out_last_first(client, db, monkeypatch):
    async def _tiny(db_, task, role):
        return "t"

    monkeypatch.setattr(context, "late_providers", [_kb, _mem])
    monkeypatch.setattr(context, "MAX_PROMPT_CHARS", len(PROMPT) + len(KB) + 2)
    me, _, run_id = await _marked(client, db)
    await late_context.fill_pending(me.id)
    run = await _run(run_id)
    assert run.prompt == "BASE\n\n" + KB + "\n\n## Answer\nyes"
    assert run.context_at is None

    # the first section does not fit: the 1-character one after it is left out too, although it would fit
    monkeypatch.setattr(context, "late_providers", [_kb, _tiny])
    monkeypatch.setattr(context, "MAX_PROMPT_CHARS", len(PROMPT) + 3)
    await _set(run_id, prompt=PROMPT, context_at=4)
    await late_context.fill_pending(me.id)
    run = await _run(run_id)
    assert run.prompt == PROMPT
    assert run.context_at is None


async def test_a_failing_provider_is_skipped(client, db, monkeypatch):
    async def boom(db_, task, role):
        raise RuntimeError("embeddings down")

    monkeypatch.setattr(context, "late_providers", [boom, _mem])
    me, _, run_id = await _marked(client, db)
    await late_context.fill_pending(me.id)
    run = await _run(run_id)
    assert run.prompt == "BASE\n\n" + MEM + "\n\n## Answer\nyes"
    assert run.context_at is None


async def test_a_failing_fill_clears_the_mark(client, db, monkeypatch, caplog):
    async def broken(db_, task, role):
        raise RuntimeError("broken")

    monkeypatch.setattr(context, "late_sections", broken)
    me, _, run_id = await _marked(client, db)
    with caplog.at_level(logging.ERROR, logger="app.agent_runs.late_context"):
        await late_context.fill_pending(me.id)
    run = await _run(run_id)
    assert run.prompt == PROMPT
    assert run.context_at is None
    assert "filling run" in caplog.text


async def test_a_run_cancelled_during_the_fill_is_not_changed(client, db, monkeypatch):
    run_ids = []

    async def cancels(db_, task, role):
        await _set(run_ids[0], status="cancelled")
        return KB

    monkeypatch.setattr(context, "late_providers", [cancels])
    me, _, run_id = await _marked(client, db)
    run_ids.append(run_id)
    await late_context.fill_pending(me.id)
    run = await _run(run_id)
    assert run.status == "cancelled"
    assert run.prompt == PROMPT
    assert run.context_at == 4


async def test_an_unmarked_or_other_owners_run_is_left_alone(client, db, monkeypatch):
    monkeypatch.setattr(context, "late_providers", [_kb, _mem])
    me, _, run_id = await _marked(client, db, at=None)
    await late_context.fill_pending(me.id)
    run = await _run(run_id)
    assert run.prompt == PROMPT and run.context_at is None

    await _set(run_id, context_at=4)
    await late_context.fill_pending(uuid.uuid4())
    run = await _run(run_id)
    assert run.prompt == PROMPT and run.context_at == 4


async def test_claim_next_skips_a_marked_run(client, db):
    me, agent, run_id = await _marked(client, db)
    conn = await _fake_conn(me, agent, _FakeSocket())
    try:
        async with SessionLocal() as s:
            assert await _claim_next(s, uuid.UUID(agent["id"]), me.id, conn.token_id) is None
        await _set(run_id, context_at=None)
        async with SessionLocal() as s:
            run = await _claim_next(s, uuid.UUID(agent["id"]), me.id, conn.token_id)
            assert run is not None and run.id == run_id
    finally:
        registry._conns.pop(me.id, None)


async def test_dispatch_fills_then_sends(client, db, monkeypatch):
    monkeypatch.setattr(context, "late_providers", [_kb, _mem])
    me, agent, run_id = await _marked(client, db)
    sock = _FakeSocket()
    await _fake_conn(me, agent, sock)
    try:
        async with SessionLocal() as s:
            await dispatch_pending(s, me.id)
            await s.commit()
        starts = [f for f in map(json.loads, sock.sent) if f["type"] == "run_start"]
        assert len(starts) == 1
        assert starts[0]["prompt"].startswith("BASE\n\n" + KB + "\n\n" + MEM + "\n\n## Answer\nyes")
        run = await _run(run_id)
        assert run.status == RunStatus.running
        assert run.context_at is None
    finally:
        registry._conns.pop(me.id, None)


async def test_dispatch_without_a_runner_still_fills(client, db, monkeypatch):
    monkeypatch.setattr(context, "late_providers", [_kb, _mem])
    me, _, run_id = await _marked(client, db)
    async with SessionLocal() as s:
        await dispatch_pending(s, me.id)
        await s.commit()
    run = await _run(run_id)
    assert run.status == RunStatus.queued
    assert KB in run.prompt
    assert run.context_at is None
