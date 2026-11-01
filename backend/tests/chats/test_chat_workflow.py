"""The task workflow, run for a chat round: no step cards, notifications that open the chat, instructions across
rounds, and the Knowledge Base and memory fed as for a task."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.chats import service as chats
from app.chats.models import Chat
from app.core.db import SessionLocal
from app.jobs.models import Job
from app.kb.models import KbFiling
from app.notifications.models import Notification
from app.tasks.models import Comment, Delivery, Task
from app.workflow import context, engine, finish
from app.workflow.models import (
    DocKind, DocStatus, Needs, RunRole, Stage, TaskWorkflow, WorkflowDocument, WorkflowStatus,
)
from tests.chats.helpers import start, world
from tests.factories import login


async def _round(db, chat: dict, n: int = 1) -> Task:
    return (await db.execute(
        select(Task).where(Task.chat_id == uuid.UUID(chat["id"]), Task.chat_round == n)
        .execution_options(populate_existing=True)
    )).scalar_one()


async def _waiting_for(db, task: Task, kind: DocKind, steps=None) -> None:
    """The round's agent submitted v1 of `kind`; the workflow waits for its approval."""
    await db.execute(update(AgentRun).where(AgentRun.task_id == task.id).values(status=RunStatus.completed))
    db.add(WorkflowDocument(task_id=task.id, kind=kind, version=1, status=DocStatus.submitted, body_md=f"# {kind}",
                            steps=steps))
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == task.id).values(
        stage=Stage.design if kind == DocKind.design else Stage.plan, status=WorkflowStatus.waiting_human,
        needs=Needs.design_approval if kind == DocKind.design else Needs.plan_approval,
    ))
    await db.commit()


async def test_approving_a_chat_plan_creates_no_subtasks(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await _waiting_for(db, rnd, DocKind.plan, steps=[{"title": "Test", "detail": "t"}, {"title": "Fix", "detail": "f"}])
    r = await client.post(f"/api/tasks/{chat['rounds'][0]['key']}/documents/plan/1/decision", json={"approve": True})
    assert r.status_code == 200, r.text
    subs = (await db.execute(select(Task).where(Task.parent_id == rnd.id))).scalars().all()
    assert subs == []


async def test_waiting_chat_notifies_starter_and_owner_with_chat_link(client, client_factory, db):
    w = await world(client, db)
    mc = client_factory()
    await login(mc, w.manager)  # a manager starts a chat with the owner's agent
    r = await mc.post("/api/chats", json={"project_key": "PAY", "message": "Fix it", "agent_id": w.agent["id"]})
    chat = r.json()
    rnd = await _round(db, chat)
    async with SessionLocal() as s:
        wf = await s.get(TaskWorkflow, rnd.id)
        await engine.wait_for(s, wf, Needs.question)
        await s.commit()
    rows = (await db.execute(select(Notification).where(Notification.kind == "needs_you"))).scalars().all()
    assert {n.user_id for n in rows} == {w.owner.id, w.manager.id}
    assert all(n.link == f"/chats/{chat['id']}" for n in rows)


async def test_finishing_a_chat_round_notifies(client, db):
    w = await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    async with SessionLocal() as s:
        wf = await s.get(TaskWorkflow, rnd.id)
        await finish.finish_workflow(s, wf, await s.get(Task, rnd.id), None)
        await s.commit()
    rows = (await db.execute(select(Notification).where(Notification.user_id == w.owner.id))).scalars().all()
    assert [n.title for n in rows if n.title.startswith("Chat finished")] == ["Chat finished: Fix the empty email crash"]


async def test_instructions_from_round_1_are_kept_in_round_2(client, db):
    w = await world(client, db)
    chat = await start(client)
    r1 = await _round(db, chat)
    db.add(Comment(task_id=r1.id, author_user_id=w.owner.id, body_md="Use RetryPolicy", to_agent_name="laptop-claude",
                   delivery=Delivery.read_while_working, created_at=datetime.now(UTC)))
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == r1.id).values(status=WorkflowStatus.finished))
    await db.commit()
    async with SessionLocal() as s:
        r2 = await chats.create_round(s, w.owner, await s.get(Chat, uuid.UUID(chat["id"])), "Also log retries")
        await s.commit()
        prompt, _ = await context.build_prompt(s, await s.get(Task, r2.id), RunRole.brainstorm)
    assert "> Use RetryPolicy" in prompt


async def test_approved_chat_design_is_filed_in_the_knowledge_base(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await _waiting_for(db, rnd, DocKind.design)
    r = await client.post(f"/api/tasks/{chat['rounds'][0]['key']}/documents/design/1/decision", json={"approve": True})
    assert r.status_code == 200, r.text
    assert (await db.execute(select(KbFiling).where(KbFiling.task_id == rnd.id))).scalars().all() != []


async def test_chat_content_feeds_memory(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    keys = set((await db.execute(select(Job.dedupe_key).where(Job.kind == "mem.extract"))).scalars())
    assert f"mem.extract:task:{rnd.id}" in keys
