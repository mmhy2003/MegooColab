"""A triggered chat's turn end: the chat ends after the reply unless the trigger keeps it open; a question or a failure
keeps it open; the starter is told as the trigger's switches say."""

import uuid

from sqlalchemy import select

from app.chats.models import Chat, ChatMode, ChatStatus
from app.chats.service import open_chat
from app.core.db import SessionLocal
from app.notifications.models import Notification
from app.projects.models import Project
from app.tasks.models import Task
from app.triggers import fire
from app.triggers.models import TriggerFiring
from app.workflow.models import WorkflowQuestion
from tests.factories import login
from tests.triggers.helpers import make_trigger
from tests.workflow.test_engine import _runs, _wf
from tests.workflow.test_freestyle_engine import _end, _queue_turn

SUBJECT = {"kind": "task", "label": "PAY-3", "title": "Fix the login", "link": "/tasks/PAY-3", "note": ""}


async def _fired(db, w, **kw) -> tuple[uuid.UUID, uuid.UUID]:
    """A trigger fired: (its chat's id, the round's task id)."""
    trigger = await make_trigger(db, w, "task_finished", any_agent=False, agent_id=w.mgr_bot.id, **kw)
    firing = TriggerFiring(trigger_id=trigger.id, event=trigger.event, subject=SUBJECT, what="PAY-3 finished.")
    db.add(firing)
    await db.commit()
    firing_id = firing.id
    await fire.tick()
    async with SessionLocal() as s:
        chat_id = (await s.get(TriggerFiring, firing_id)).chat_id
        task_id = await s.scalar(select(Task.id).where(Task.chat_id == chat_id))
    return chat_id, task_id


async def _first_run(task_id):
    [run] = await _runs(task_id)
    return run


async def _chat(chat_id) -> Chat:
    async with SessionLocal() as s:
        return await s.get(Chat, chat_id)


async def _notes(user_id, task_id) -> list[tuple[str, str]]:
    async with SessionLocal() as s:
        rows = await s.execute(select(Notification).where(Notification.user_id == user_id,
                                                          Notification.task_id == task_id))
        return [(n.kind, n.title) for n in rows.scalars()]


async def _state(client, w, chat_id) -> str:
    await login(client, w.manager)
    r = await client.get(f"/api/chats/{chat_id}")
    assert r.status_code == 200, r.text
    return r.json()["state"]


async def test_the_chat_ends_after_the_reply_by_default(client, db, world):
    chat_id, task_id = await _fired(db, world)
    await _end((await _first_run(task_id)).id, "completed", "Wrote the notes")

    chat = await _chat(chat_id)
    assert chat.status == ChatStatus.ended and chat.ended_at is not None
    assert chat.last_activity_at == chat.ended_at
    wf = await _wf(task_id)
    assert (wf.status, wf.stage, wf.needs) == ("finished", "done", None)
    # the reply is told, the end is not: no "Chat finished"
    [(kind, title)] = await _notes(world.manager.id, task_id)
    assert kind == "agent_replied" and title.endswith(f"replied in {chat.title}")


async def test_keep_open_keeps_the_chat_waiting_for_a_reply(client, db, world):
    chat_id, task_id = await _fired(db, world, keep_open=True)
    await _end((await _first_run(task_id)).id, "completed", "Wrote the notes")

    assert (await _chat(chat_id)).status == ChatStatus.open
    assert (await _wf(task_id)).needs == "reply"
    assert await _state(client, world, chat_id) == "reply"


async def test_a_question_keeps_it_open(client, db, world):
    chat_id, task_id = await _fired(db, world)
    run = await _first_run(task_id)
    async with SessionLocal() as s:
        s.add(WorkflowQuestion(task_id=task_id, run_id=run.id, stage="build", body="Which tag?", choices=[]))
        await s.commit()
    await _end(run.id, "completed")

    assert (await _chat(chat_id)).status == ChatStatus.open
    assert await _state(client, world, chat_id) == "question"


async def test_a_failed_turn_keeps_it_open(client, db, world):
    chat_id, task_id = await _fired(db, world)
    await _end((await _first_run(task_id)).id, "failed", reason="agent_error")

    assert (await _chat(chat_id)).status == ChatStatus.open
    wf = await _wf(task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "reply")


async def test_notifications_follow_the_switches(client, db, world):
    # the reply is told by default
    _, told = await _fired(db, world, name="Told")
    await _end((await _first_run(told)).id, "completed", "Done")
    assert [k for k, _ in await _notes(world.manager.id, told)] == ["agent_replied"]

    # notify_reply off: the firing's own reply is not told
    _, quiet = await _fired(db, world, name="Quiet", notify_reply=False)
    await _end((await _first_run(quiet)).id, "completed", "Done")
    assert await _notes(world.manager.id, quiet) == []

    # notify_problems off: the firing's own failure is not told; notify_reply doesn't silence a failure
    _, no_problems = await _fired(db, world, name="No problems", notify_problems=False)
    await _end((await _first_run(no_problems)).id, "failed", reason="agent_error")
    assert await _notes(world.manager.id, no_problems) == []
    _, failing = await _fired(db, world, name="Failing", notify_reply=False)
    await _end((await _first_run(failing)).id, "failed", reason="agent_error")
    assert [k for k, _ in await _notes(world.manager.id, failing)] == ["agent_replied"]

    # later turns are told as before, whatever the switches
    _, later = await _fired(db, world, name="Later", keep_open=True, notify_reply=False)
    await _end((await _first_run(later)).id, "completed", "Done")
    assert await _notes(world.manager.id, later) == []
    second = await _queue_turn(later, world.manager.id)
    await _end(second.id, "completed", "Pushed")
    assert [k for k, _ in await _notes(world.manager.id, later)] == ["agent_replied"]


async def test_ordinary_freestyle_chats_are_unchanged(client, db, world):
    project = await db.get(Project, uuid.UUID(world.project["id"]))
    chat, task = await open_chat(db, world.manager, project, world.mgr_bot, "Bump it.", ChatMode.freestyle)
    await db.commit()
    chat_id, task_id = chat.id, task.id
    await _end((await _first_run(task_id)).id, "completed", "Done")

    assert (await _chat(chat_id)).status == ChatStatus.open
    assert (await _wf(task_id)).needs == "reply"
    assert [k for k, _ in await _notes(world.manager.id, task_id)] == ["agent_replied"]
