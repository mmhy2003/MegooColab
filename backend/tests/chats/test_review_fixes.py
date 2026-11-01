"""The final review's findings, each pinned: needs-you visibility, a stale chat, a paused round, step cards of a round
in review, a closed project, and the cheap waiting count."""

import uuid

from sqlalchemy import select, update

from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunStatus
from app.chats import service
from app.chats.models import Chat
from app.core.db import SessionLocal
from app.projects.models import BoardColumn, Project, ProjectStatus
from app.tasks.models import Comment, Task
from app.workflow.models import (
    DocKind, DocStatus, Needs, Stage, TaskWorkflow, WorkflowDocument, WorkflowStatus,
)
from tests.chats.helpers import start, world
from tests.chats.test_chat_workflow import _round
from tests.chats.test_rounds import _finished
from tests.factories import login


async def _waiting_question(db, task: Task) -> None:
    await db.execute(update(AgentRun).where(AgentRun.task_id == task.id).values(status=RunStatus.completed))
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == task.id).values(
        status=WorkflowStatus.waiting_human, needs=Needs.question,
    ))
    await db.commit()


async def test_needs_you_hides_a_chat_from_members_outside_it(client, client_factory, db):
    w = await world(client, db)
    chat = await start(client)
    await _waiting_question(db, await _round(db, chat))
    oc = client_factory()
    await login(oc, w.other)
    d = (await oc.get("/api/dashboard")).json()
    assert all(n.get("chat_id") is None and n["ref"] != chat["rounds"][0]["key"] for n in d["needs"])
    assert d["numbers"]["need_you"] == 0


async def test_a_message_after_the_chat_ended_elsewhere_is_refused(client, db):
    w = await world(client, db)
    chat = await start(client)
    await _finished(db, await _round(db, chat), "merged_local")
    async with SessionLocal() as s:
        stale = await s.get(Chat, uuid.UUID(chat["id"]))  # loaded while the chat is open
        assert (await client.post(f"/api/chats/{chat['id']}/end")).status_code == 200
        try:
            await service.send_message(s, w.owner, stale, "One more thing")
        except Exception as e:  # noqa: BLE001
            assert getattr(e, "detail", None) == "chat_ended"
        else:
            raise AssertionError("a new round started in an ended chat")
    assert len((await client.get(f"/api/chats/{chat['id']}")).json()["rounds"]) == 1


async def test_a_message_restarts_a_paused_round(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await db.execute(update(AgentRun).where(AgentRun.task_id == rnd.id).values(status=RunStatus.cancelled))
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == rnd.id).values(
        status=WorkflowStatus.paused, needs=None,
    ))
    await db.commit()
    assert (await client.get(f"/api/chats/{chat['id']}")).json()["intent"] == "restart"
    r = await client.post(f"/api/chats/{chat['id']}/messages", json={"body": "Carry on, use RetryPolicy"})
    assert r.status_code == 201 and r.json()["intent"] == "restart"
    wf = await db.get(TaskWorkflow, rnd.id, populate_existing=True)
    assert wf.status != WorkflowStatus.paused
    runs = (await db.execute(select(AgentRun).where(AgentRun.task_id == rnd.id, AgentRun.status.in_(ACTIVE_STATUSES)))).scalars().all()
    assert runs
    c = (await db.execute(select(Comment).where(Comment.task_id == rnd.id))).scalar_one()
    assert c.body_md == "Carry on, use RetryPolicy" and c.delivery is not None


async def test_a_round_in_code_review_goes_on_the_board_with_its_steps_done(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    db.add(WorkflowDocument(task_id=rnd.id, kind=DocKind.plan, version=1, status=DocStatus.approved, body_md="# p",
                            steps=[{"title": "A", "detail": "a", "subtask_id": None},
                                   {"title": "B", "detail": "b", "subtask_id": None}]))
    await db.execute(update(AgentRun).where(AgentRun.task_id == rnd.id).values(status=RunStatus.completed))
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == rnd.id).values(
        status=WorkflowStatus.waiting_human, needs=Needs.human_code_review, stage=Stage.done, current_step=None,
    ))
    await db.commit()
    await client.post(f"/api/chats/{chat['id']}/end")
    r = await client.post(f"/api/chats/{chat['id']}/rounds/1/board", json={"add": True})
    assert r.status_code == 200, r.text
    subs = (await db.execute(select(Task).where(Task.parent_id == rnd.id))).scalars().all()
    cats = {(await db.get(BoardColumn, s.column_id)).category for s in subs}
    assert len(subs) == 2 and cats == {"done"}


async def test_a_closed_project_takes_no_chat_messages(client, db):
    await world(client, db)
    chat = await start(client)
    await _finished(db, await _round(db, chat), "merged_local")
    await db.execute(update(Project).where(Project.key == "PAY").values(status=ProjectStatus.finished))
    await db.commit()
    r = await client.post(f"/api/chats/{chat['id']}/messages", json={"body": "Another round"})
    assert r.status_code == 409 and r.json()["detail"] == "project_closed"
    r = await client.post(f"/api/chats/{chat['id']}/rounds/1/board", json={"add": True})
    assert r.status_code == 409 and r.json()["detail"] == "project_closed"


async def test_the_waiting_count_is_cheap_and_right(client, client_factory, db):
    w = await world(client, db)
    chat = await start(client)
    assert (await client.get("/api/chats/count")).json() == {"waiting": 0}
    await _waiting_question(db, await _round(db, chat))
    assert (await client.get("/api/chats/count")).json() == {"waiting": 1}
    oc = client_factory()
    await login(oc, w.other)
    assert (await oc.get("/api/chats/count")).json() == {"waiting": 0}
