"""Ending a run or approving a document never holds the task, workflow or run lock while the Knowledge Base
and Memory sections wait on the embeddings provider, and a comment to the agent is not held up (MC-215)."""

import asyncio

from sqlalchemy import select, text

from app.agent_runs.models import AgentRun
from app.agent_runs.service import dispatch_pending
from app.ai import client as ai
from app.core.db import SessionLocal
from app.kb import access
from app.tasks.models import Task
from app.workflow import context, engine
from app.workflow.models import TaskWorkflow
from tests.factories import DEFAULT_PASSWORD
from tests.workflow.test_documents import _design_waiting, _submit
from tests.workflow.test_engine import _finish, _runs, _started


async def _login(client, user):
    r = await client.post("/api/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD})
    assert r.status_code == 200, r.text


def _probe_embeds(monkeypatch, client, task_id, key) -> list[str]:
    """While each embedding call waits, another transaction locks the task, its workflow and its runs (giving up
    after 200 ms), and a comment to the agent goes through the API. Each probe adds "free" or what went wrong."""
    real, seen, busy = ai.embed, [], []

    async def embed(db, texts, **kw):
        if not busy:  # the comment's own request must not probe again
            busy.append(True)
            try:
                async with SessionLocal() as other:
                    await other.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    await other.execute(select(Task.id).where(Task.id == task_id).with_for_update(key_share=True))
                    await other.execute(
                        select(TaskWorkflow.task_id).where(TaskWorkflow.task_id == task_id).with_for_update())
                    await other.execute(select(AgentRun.id).where(AgentRun.task_id == task_id).with_for_update())
                    await other.rollback()
                r = await asyncio.wait_for(client.post(
                    f"/api/tasks/{key}/comments", json={"body_md": "Log retries", "to_agent": True}), 2)
                seen.append("free" if r.status_code == 201 else f"comment {r.status_code}: {r.text}")
            except Exception as exc:  # noqa: BLE001 - the providers swallow errors, so the probe keeps them
                seen.append(repr(exc))
            finally:
                busy.clear()
        return await real(db, texts, **kw)

    monkeypatch.setattr(ai, "embed", embed)
    return seen


async def test_ending_a_run_embeds_without_holding_locks(db, tc_factory, client, monkeypatch):
    tc = tc_factory(lifespan=True)  # registers the Knowledge Base and Memory providers
    await access.ensure_spaces(db)
    await db.commit()
    b, run = await _started(db, tc)
    await _login(client, b.manager)
    seen = _probe_embeds(monkeypatch, client, b.task_id, b.key)
    await _finish(b.manager.id, run, "failed")  # the retry is queued under the run's ending locks
    assert seen and set(seen) == {"free"}, seen
    retry = (await _runs(b.task_id))[-1]
    assert retry.id != run.id and retry.context_at is None


async def test_approving_a_design_embeds_without_holding_locks(db, tc_factory, client, monkeypatch):
    tc = tc_factory(lifespan=True)
    await access.ensure_spaces(db)
    await db.commit()
    b, _ = await _design_waiting(db, tc)
    await _login(client, b.manager)
    seen = _probe_embeds(monkeypatch, client, b.task_id, b.key)
    r = await client.post(f"/api/tasks/{b.key}/documents/design/1/decision", json={"approve": True})
    assert r.status_code == 200, r.text
    assert seen and set(seen) == {"free"}, seen
    plan_run = (await _runs(b.task_id))[-1]
    assert plan_run.workflow_role == "plan" and plan_run.context_at is None


async def _plan_ready(db, tc):
    """A design waiting for approval: the next enqueue may be called directly."""
    b, run = await _started(db, tc)
    await _submit(b, run)
    await _finish(b.manager.id, run, "completed")
    return b


async def test_enqueue_marks_the_place_and_calls_no_late_provider(db, tc_factory, monkeypatch):
    tc = tc_factory(lifespan=True)
    b = await _plan_ready(db, tc)
    calls = []

    async def spy(db_, task_, role_):
        calls.append(role_)
        return "## Knowledge Base\nspy"

    monkeypatch.setattr(context, "late_providers", [spy])
    async with SessionLocal() as s:
        wf = await engine.lock_workflow(s, b.task_id)
        task = await s.get(Task, b.task_id)
        await engine.set_stage(s, wf, task, "plan")
        run = await engine.enqueue(s, wf, task, "plan", requested_by=b.manager.id,
                                   resume_kind="nudge", payload="Keep going")
        assert calls == []
        assert run.prompt[run.context_at:].startswith("\n\n## Reminder\n")
        await s.commit()  # committed, never dispatched: as after a crash
    assert (await _runs(b.task_id))[-1].context_at == run.context_at
    async with SessionLocal() as s:  # the next dispatch for the owner fills it
        await dispatch_pending(s, b.manager.id)
        await s.commit()
    filled = (await _runs(b.task_id))[-1]
    assert calls == ["plan"] and filled.context_at is None
    assert "## Knowledge Base\nspy\n\n## Reminder\n" in filled.prompt
