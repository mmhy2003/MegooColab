"""The Knowledge Base and Memory sections are added after the commit, before the run is sent (MC-215)."""

import logging
import uuid

from sqlalchemy import update

from app.agent_runs import late_context
from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.workflow import context
from tests.agent_runs.test_dispatch import _offline_runs

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
