"""A message typed in a chat does what the chat is waiting for, decided when it is sent."""

import uuid

from sqlalchemy import select, update

from app.agent_runs.models import ACTIVE_STATUSES, AgentRun
from app.chats.models import Chat, ChatStatus
from app.tasks.models import Comment, Task
from app.workflow.models import DocKind, DocStatus, QuestionStatus, WorkflowDocument, WorkflowQuestion
from tests.chats.helpers import start, world
from tests.chats.test_chat_workflow import _round, _waiting_for
from tests.factories import login
from tests.workflow.test_engine import _ask, _finish


async def _send(client, chat, body):
    return await client.post(f"/api/chats/{chat['id']}/messages", json={"body": body})


async def _run(db, task: Task) -> AgentRun:
    return (await db.execute(
        select(AgentRun).where(AgentRun.task_id == task.id, AgentRun.status.in_(ACTIVE_STATUSES))
        .execution_options(populate_existing=True)
    )).scalar_one()


async def _intent(client, chat) -> str:
    return (await client.get(f"/api/chats/{chat['id']}")).json()["intent"]


async def test_message_answers_the_open_question(client, db):
    w = await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    run = await _run(db, rnd)
    qid = await _ask(rnd.id, run.id)
    await _finish(w.owner.id, run)
    assert await _intent(client, chat) == "answer"
    r = await _send(client, chat, "Postgres, please")
    assert r.status_code == 201 and r.json() == {"intent": "answer", "round_key": chat["rounds"][0]["key"]}
    q = await db.get(WorkflowQuestion, qid, populate_existing=True)
    assert q.status != QuestionStatus.open and q.answer_text == "Postgres, please"
    assert await _run(db, rnd)  # the brainstorm session goes on


async def test_message_while_plan_waits_asks_for_changes(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await _waiting_for(db, rnd, DocKind.plan, steps=[{"title": "One", "detail": "d"}])
    assert await _intent(client, chat) == "changes"
    assert (await _send(client, chat, "Split it in two")).json()["intent"] == "changes"
    doc = (await db.execute(select(WorkflowDocument).where(WorkflowDocument.task_id == rnd.id)
                            .execution_options(populate_existing=True))).scalar_one()
    assert doc.status == DocStatus.rejected and doc.decision_comment == "Split it in two"
    assert await _run(db, rnd)  # the plan session revises it


async def test_message_while_working_tells_the_agent(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    assert await _intent(client, chat) == "tell"  # its run is queued
    assert (await _send(client, chat, "Use the existing validator")).json()["intent"] == "tell"
    c = (await db.execute(select(Comment).where(Comment.task_id == rnd.id))).scalar_one()
    assert c.body_md == "Use the existing validator" and c.delivery == "waiting"


async def test_message_follows_the_state_at_send_time(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    assert await _intent(client, chat) == "tell"
    await _waiting_for(db, rnd, DocKind.plan, steps=[{"title": "One", "detail": "d"}])  # meanwhile: the plan arrives
    assert (await _send(client, chat, "Split it")).json()["intent"] == "changes"


async def test_a_second_reply_to_a_decided_plan_does_not_decide_it_again(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await _waiting_for(db, rnd, DocKind.plan, steps=[{"title": "One", "detail": "d"}])
    assert (await _send(client, chat, "Split it")).json()["intent"] == "changes"
    # the plan session is now revising: a second message goes to it, it does not reject anything again
    assert (await _send(client, chat, "And name step 2 'Validate'")).json()["intent"] == "tell"
    docs = (await db.execute(select(WorkflowDocument).where(WorkflowDocument.task_id == rnd.id))).scalars().all()
    assert [d.status for d in docs] == [DocStatus.rejected]


async def test_message_to_an_ended_chat_is_409(client, db):
    await world(client, db)
    chat = await start(client)
    await db.execute(update(Chat).where(Chat.id == uuid.UUID(chat["id"])).values(status=ChatStatus.ended))
    await db.commit()
    assert await _intent(client, chat) == "closed"
    r = await _send(client, chat, "Hello?")
    assert r.status_code == 409 and r.json()["detail"] == "chat_ended"


async def test_someone_outside_the_chat_cannot_message_it(client, client_factory, db):
    w = await world(client, db)
    chat = await start(client)
    oc = client_factory()
    await login(oc, w.other)
    assert (await _send(oc, chat, "Hi")).status_code == 404
