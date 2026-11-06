"""Freestyle chats in the chat service: a chat started in freestyle mode runs one round of turns, each message the
next turn; waiting for a reply is not Needs you; End chat finishes the round (freestyle chats, Task 4)."""

import uuid

from sqlalchemy import select

from app.chats.models import Chat
from app.core.db import SessionLocal
from app.notifications.models import Notification
from app.runner.registry import registry
from app.tasks.models import Comment, Task
from app.workflow.models import WorkflowQuestion
from tests.chats.helpers import start, world
from tests.chats.test_chat_workflow import _round
from tests.factories import login
from tests.workflow.test_engine import _runs, _wf
from tests.workflow.test_freestyle_engine import _end


async def _chat(client, chat) -> dict:
    r = await client.get(f"/api/chats/{chat['id']}")
    assert r.status_code == 200, r.text
    return r.json()


async def _replied(client, db) -> tuple[dict, Task]:
    """A freestyle chat whose first turn completed: it waits for the person's reply."""
    await world(client, db)
    chat = await start(client, mode="freestyle")
    rnd = await _round(db, chat)
    [run] = await _runs(rnd.id)
    await _end(run.id, "completed", "Done")
    return chat, rnd


async def test_starting_a_freestyle_chat_runs_a_freestyle_turn(client, db, monkeypatch):
    await world(client, db)
    monkeypatch.setattr(registry, "is_available", lambda agent_id: True)  # its runner is connected
    chat = await start(client, mode="freestyle")
    assert (chat["mode"], chat["state"], chat["intent"]) == ("freestyle", "working", "tell")
    runs = await _runs((await _round(db, chat)).id)
    assert [(r.workflow_role, r.status) for r in runs] == [("freestyle", "queued")]


async def test_a_reply_starts_the_next_turn_with_the_message(client, db):
    chat, rnd = await _replied(client, db)
    out = await _chat(client, chat)
    assert (out["state"], out["intent"]) == ("reply", "turn")
    r = await client.post(f"/api/chats/{chat['id']}/messages", json={"body": "push it"})
    assert r.status_code == 201, r.text
    assert r.json()["intent"] == "turn"
    runs = await _runs(rnd.id)
    assert [(r.workflow_role, r.status) for r in runs] == [("freestyle", "completed"), ("freestyle", "queued")]
    comment = (await db.execute(
        select(Comment).where(Comment.task_id == rnd.id, Comment.body_md == "push it")
    )).scalar_one()
    assert comment.delivery == "waiting" and comment.to_agent_id is not None
    assert len((await _chat(client, chat))["rounds"]) == 1
    assert (await _wf(rnd.id)).status == "running"


async def test_a_freestyle_chat_waiting_for_a_reply_is_not_needs_you(client, db):
    chat, rnd = await _replied(client, db)
    d = (await client.get("/api/dashboard")).json()
    assert not [n for n in d["needs"] if n.get("chat_id") == chat["id"]]
    assert d["numbers"]["chats_waiting_on_you"] == 0
    assert (await client.get("/api/dashboard/count")).json()["needs_you"] == 0
    assert (await client.get("/api/chats/count")).json() == {"waiting": 0}
    r = await client.get("/api/projects/PAY/tasks", params={"needs_you": "true"})
    assert r.status_code == 200, r.text
    assert not [t for t in r.json() if t["id"] == str(rnd.id)]


async def test_a_freestyle_question_is_needs_you(client, db):
    await world(client, db)
    chat = await start(client, mode="freestyle")
    rnd = await _round(db, chat)
    [run] = await _runs(rnd.id)
    async with SessionLocal() as s:
        s.add(WorkflowQuestion(task_id=rnd.id, run_id=run.id, stage="build", body="Which tag?", choices=[]))
        await s.commit()
    await _end(run.id, "completed")
    out = await _chat(client, chat)
    assert (out["state"], out["intent"]) == ("question", "answer")
    assert (await client.get("/api/chats/count")).json() == {"waiting": 1}


async def test_ending_a_freestyle_chat_finishes_its_round_even_mid_turn(client, db):
    await world(client, db)
    chat = await start(client, mode="freestyle")
    rnd = await _round(db, chat)
    [run] = await _runs(rnd.id)
    assert run.status == "queued"
    r = await client.post(f"/api/chats/{chat['id']}/end")
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["state"], r.json()["intent"]) == ("ended", "ended", "closed")
    [run] = await _runs(rnd.id)
    assert run.status == "cancelled"
    wf = await _wf(rnd.id)
    assert (wf.status, wf.stage, wf.needs) == ("finished", "done", None) and wf.finished_at is not None
    assert r.json()["rounds"][0]["board"] == "pending"
    d = await client.get(f"/api/chats/{chat['id']}/rounds/1/board")
    assert d.status_code == 200, d.text
    from app.projects.models import BoardColumn

    assert (await db.get(BoardColumn, uuid.UUID(d.json()["column_id"]))).category == "done"


async def test_ending_a_freestyle_chat_waiting_for_a_reply_finishes_it(client, db):
    chat, rnd = await _replied(client, db)
    r = await client.post(f"/api/chats/{chat['id']}/end")
    assert r.status_code == 200, r.text
    wf = await _wf(rnd.id)
    assert (wf.status, wf.stage, wf.needs) == ("finished", "done", None)
    assert len(await _runs(rnd.id)) == 1


async def test_a_freestyle_turn_notifies_the_chat_starter(client, client_factory, db):
    w = await world(client, db)
    mc = client_factory()
    await login(mc, w.manager)  # a manager starts a freestyle chat with the owner's agent
    r = await mc.post("/api/chats", json={"project_key": "PAY", "message": "Bump the version",
                                          "agent_id": w.agent["id"], "mode": "freestyle"})
    assert r.status_code == 201, r.text
    chat = r.json()
    rnd = await _round(db, chat)
    [run] = await _runs(rnd.id)
    await _end(run.id, "completed", "Done")
    rows = (await db.execute(select(Notification).where(Notification.task_id == rnd.id))).scalars().all()
    title = (await db.get(Chat, uuid.UUID(chat["id"]))).title
    assert [(n.user_id, n.kind, n.title, n.link) for n in rows] == [
        (w.manager.id, "agent_replied", f"laptop-claude replied in {title}", f"/chats/{chat['id']}")
    ]
    assert not [n for n in rows if n.kind == "needs_you"]


async def test_workflow_chats_are_unchanged(client, db):
    await world(client, db)
    chat = await start(client)
    assert chat["mode"] == "workflow"
    rnd = await _round(db, chat)
    assert [r.workflow_role for r in await _runs(rnd.id)] == ["brainstorm"]
    r = await client.post(f"/api/chats/{chat['id']}/end")
    assert r.status_code == 200, r.text
    assert (await _wf(rnd.id)).status == "paused"
