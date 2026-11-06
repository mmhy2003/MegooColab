"""A freestyle turn in the engine: one writing run per turn; its end waits for the next message, never retries or
escalates (freestyle chats, Task 2). Until chats start freestyle rounds, these run on a fresh board task."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.auth.models import User
from app.core.db import SessionLocal
from app.notifications.models import Notification
from app.tasks.models import Comment, Delivery, Task, TaskEvent
from app.workflow import engine, freestyle
from app.workflow.models import RunRole, WorkflowQuestion
from tests.chats.helpers import world
from tests.workflow.test_engine import _events, _finish, _runs, _wf


async def _end(run_id, status="completed", summary=None, reason=None):
    async with SessionLocal() as s:
        run = await s.get(AgentRun, run_id)
        await engine.lock_workflow(s, run.task_id)
        run.status, run.summary = status, summary
        if reason:
            run.reason = reason
        await engine.on_run_finished(s, run)
        await s.commit()


async def _freestyle(client, db):
    """A board task on the world's agent, started as a freestyle round: (world, task id, its first run)."""
    w = await world(client, db)
    body = {"title": "Bump the version", "assignee_agent_id": w.agent["id"]}
    r = await client.post("/api/projects/PAY/tasks", json=body)
    assert r.status_code == 201, r.text
    task_id = uuid.UUID(r.json()["id"])
    async with SessionLocal() as s:
        task = await s.get(Task, task_id)
        await engine.start_freestyle(s, await s.get(User, w.owner.id), task)
        await s.commit()
    [run] = await _runs(task_id)
    return w, task_id, run


async def _queue_turn(task_id, owner_id) -> AgentRun:
    async with SessionLocal() as s:
        wf = await engine.lock_workflow(s, task_id)
        run = await freestyle.queue_turn(s, wf, await s.get(Task, task_id), requested_by=owner_id)
        await s.commit()
        return run


async def _waiting_comment(task_id, w, body="also tag it", *, after: AgentRun, **fields):
    """A message for the agent, sent a second after `after` was queued (while that turn was queued or working)."""
    async with SessionLocal() as s:
        s.add(Comment(task_id=task_id, author_user_id=w.owner.id, body_md=body, to_agent_id=uuid.UUID(w.agent["id"]),
                      delivery=Delivery.waiting, created_at=after.created_at + timedelta(seconds=1), **fields))
        await s.commit()


async def _notifications(user_id, task_id) -> list[Notification]:
    async with SessionLocal() as s:
        rows = await s.execute(select(Notification).where(Notification.user_id == user_id,
                                                          Notification.task_id == task_id))
        return list(rows.scalars())


async def _task(task_id) -> Task:
    async with SessionLocal() as s:
        return await s.get(Task, task_id)


async def test_start_freestyle_queues_one_writing_turn(client, db):
    _, task_id, run = await _freestyle(client, db)
    wf = await _wf(task_id)
    assert (wf.driver, wf.stage, wf.enforcement, wf.status) == ("runner", "build", "unenforced", "running")
    assert (run.workflow_role, run.policy, run.status) == ("freestyle", "workspace", "queued")
    assert not [r for r in await _runs(task_id) if r.workflow_role == "brainstorm"]


async def test_completed_turn_waits_for_a_reply_and_notifies_once(client, db):
    w, task_id, run = await _freestyle(client, db)
    await _end(run.id, "completed", "Done: bumped VERSION")
    wf = await _wf(task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "reply")
    notes = await _notifications(w.owner.id, task_id)
    # not in a chat: the agent's owner stands in for the chat's starter, linked to the board
    assert [(n.kind, n.title, n.body) for n in notes] == [
        ("agent_replied", f"laptop-claude replied on PAY-{(await _task(task_id)).number}", "Done: bumped VERSION")
    ]
    assert notes[0].link.startswith("/projects/PAY/board?task=PAY-")
    assert not [n for n in notes if n.kind == "needs_you"]


async def test_notification_body_is_the_whole_reply_not_the_last_chunk(client, db):
    w, task_id, run = await _freestyle(client, db)
    async with SessionLocal() as s:
        for i, text in enumerate(["Created release/", "2026.11.06.208"]):
            s.add(TaskEvent(task_id=task_id, kind="agent_message", data={"text": text, "run_id": str(run.id)},
                            created_at=run.created_at + timedelta(seconds=i + 1)))
        await s.commit()
    await _end(run.id, "completed", "2026.11.06.208")
    [note] = await _notifications(w.owner.id, task_id)
    assert note.body.startswith("Created release/2026.11.06.208")


async def test_failed_turns_never_retry_or_escalate(client, db):
    w, task_id, run = await _freestyle(client, db)
    for i in range(3):
        await _end(run.id, "failed", reason="agent_error" if i == 0 else None)
        wf = await _wf(task_id)
        assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "reply", None)
        assert wf.failures == 0
        notes = [n for n in await _notifications(w.owner.id, task_id) if n.kind == "agent_replied"]
        assert len(notes) == i + 1  # exactly one per failed turn (the person reads it before the next: unread repeats
        async with SessionLocal() as s:  # for the same task are folded by notify, as for replies)
            for n in notes:
                (await s.get(Notification, n.id)).read_at = datetime.now(UTC)
            await s.commit()
        runs = await _runs(task_id)
        assert len(runs) == i + 1 and runs[-1].id == run.id  # nothing queued after the failure
        if i < 2:
            run = await _queue_turn(task_id, w.owner.id)  # as the person's next message will
    assert not await _events(task_id, "workflow.escalated")
    notes = await _notifications(w.owner.id, task_id)
    key = f"PAY-{(await _task(task_id)).number}"
    assert sorted((n.kind, n.title, n.body) for n in notes) == sorted(
        [("agent_replied", f"laptop-claude couldn't finish {key}", "agent error")]
        + [("agent_replied", f"laptop-claude couldn't finish {key}", "the run failed")] * 2
    )
    assert all(n.link.startswith("/projects/PAY/board?task=PAY-") for n in notes)
    assert not [n for n in notes if n.kind == "needs_you"]


async def test_message_left_waiting_starts_the_next_turn(client, db):
    w, task_id, run = await _freestyle(client, db)
    await _waiting_comment(task_id, w, after=run)
    await _end(run.id, "completed")
    runs = await _runs(task_id)
    assert len(runs) == 2 and (runs[1].workflow_role, runs[1].status) == ("freestyle", "queued")
    assert (await _wf(task_id)).status == "running"
    # after a failed turn a waiting message does not start another one: it goes with the next message's turn
    await _waiting_comment(task_id, w, "and push it", after=runs[1])
    await _end(runs[1].id, "failed")
    assert len(await _runs(task_id)) == 2
    wf = await _wf(task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "reply")


async def test_question_in_a_turn_waits_for_the_answer(client, db):
    _, task_id, run = await _freestyle(client, db)
    async with SessionLocal() as s:
        s.add(WorkflowQuestion(task_id=task_id, run_id=run.id, stage="build", body="Which tag?", choices=[]))
        await s.commit()
    await _end(run.id, "completed")
    wf = await _wf(task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "question")


async def test_engine_error_in_a_freestyle_turn_waits_for_a_reply(client, db, monkeypatch):
    _, task_id, run = await _freestyle(client, db)

    async def broken(*_):
        raise RuntimeError("boom")

    monkeypatch.setitem(engine.ROLE_HANDLERS, RunRole.freestyle, broken)
    await _end(run.id, "completed")
    wf = await _wf(task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "reply", None)
    assert not await _events(task_id, "workflow.escalated")


async def test_start_freestyle_refuses_an_active_workflow(client, db):
    w, task_id, _ = await _freestyle(client, db)
    async with SessionLocal() as s:
        with pytest.raises(HTTPException) as e:
            await engine.start_freestyle(s, await s.get(User, w.owner.id), await s.get(Task, task_id))
    assert e.value.detail == "workflow_active"
    assert len(await _runs(task_id)) == 1


async def test_unasked_cancel_waits_but_a_person_cancel_pauses(client, db):
    w, task_id, run = await _freestyle(client, db)
    await _end(run.id, "cancelled")  # a lost connection: nobody asked
    wf = await _wf(task_id)
    assert (wf.status, wf.needs, wf.failures) == ("waiting_human", "reply", 0)
    run = await _queue_turn(task_id, w.owner.id)
    async with SessionLocal() as s:
        row = await s.get(AgentRun, run.id)
        row.cancelled_by = w.owner.id
        await s.commit()
    await _end(run.id, "cancelled")
    assert (await _wf(task_id)).status == "paused"


async def test_a_turn_with_no_output_does_not_restart_on_its_own_message(client, db):
    """The message the turn started with comes back to waiting when the agent never worked (release_on_run_end):
    it goes with the turn the person's next message starts, not a turn of its own, again and again."""
    w, task_id, run = await _freestyle(client, db)
    async with SessionLocal() as s:  # what the turn's start did: it took the message sent before it was queued
        s.add(Comment(task_id=task_id, author_user_id=w.owner.id, body_md="bump the version",
                      to_agent_id=uuid.UUID(w.agent["id"]), delivery=Delivery.given_at_start, delivery_run_id=run.id,
                      created_at=run.created_at - timedelta(seconds=1)))
        await s.commit()
    await _finish(w.owner.id, run, "completed")  # the real end of a run: no agent output, so the message is released
    async with SessionLocal() as s:
        [c] = (await s.execute(select(Comment).where(Comment.task_id == task_id))).scalars().all()
        assert c.delivery == "waiting"
    assert len(await _runs(task_id)) == 1
    wf = await _wf(task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "reply")
