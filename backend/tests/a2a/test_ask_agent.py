"""Agents asking other projects on their own: wait, follow-ups, the per-task limit and the per-user cap."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.a2a import service
from app.a2a.models import Question, QuestionStatus
from app.agents.models import Agent
from app.auth.models import User
from app.chats.models import Chat
from app.core.db import SessionLocal
from app.projects.models import Project
from app.tasks.models import Task, TaskEvent
from tests.a2a.test_ask import _world
from tests.factories import make_project

BODY = "What payload does /orders/sync send?"


async def _agent(db, owner) -> uuid.UUID:
    agent = Agent(owner_id=owner.id, name=f"asker-{uuid.uuid4().hex[:4]}", program="claude_code")
    db.add(agent)
    await db.commit()
    return agent.id


async def _agent_ask(asker, agent_id, task_key="QAA-1", project_key="QBB", **kw) -> Question:
    async with SessionLocal() as s:
        user = await s.get(User, asker.id)
        q, _ = await service.ask(s, user, project_key=project_key, body=BODY, task_key=task_key, agent_id=agent_id, **kw)
        await s.commit()
        return q


async def _person_ask(asker, task_key="QAA-1", **kw) -> Question:
    async with SessionLocal() as s:
        user = await s.get(User, asker.id)
        q, _ = await service.ask(s, user, project_key="QBB", body=BODY, task_key=task_key, **kw)
        await s.commit()
        return q


async def _refused(coro) -> HTTPException:
    with pytest.raises(HTTPException) as e:
        await coro
    return e.value


async def _second_task(a) -> None:
    r = await a.post("/api/projects/QAA/tasks", json={"title": "Second", "type": "task"})
    assert r.status_code == 201, r.text


async def _chat_of_two_rounds(db, asker) -> None:
    """QAA-1 and QAA-2 become rounds 1 and 2 of one chat."""
    project_id = await db.scalar(select(Project.id).where(Project.key == "QAA"))
    chat = Chat(project_id=project_id, started_by=asker.id, title="Chat")
    db.add(chat)
    await db.flush()
    for n in (1, 2):
        await db.execute(update(Task).where(Task.project_id == project_id, Task.number == n)
                         .values(chat_id=chat.id, chat_round=n))
    await db.commit()


async def test_ask_stores_wait_and_follow_up(client_factory, db):
    asker, _t, _o, _a, _b, _c = await _world(client_factory, db)
    agent_id = await _agent(db, asker)
    q1 = await _agent_ask(asker, agent_id)
    q2 = await _agent_ask(asker, agent_id, wait=True, follow_up_to="QBB-Q1")
    assert q2.wait is True and q2.follow_up_of_id == q1.id and q1.wait is False
    event = (await db.execute(select(TaskEvent).where(TaskEvent.kind == "question_asked")
                              .order_by(TaskEvent.created_at.desc()).limit(1))).scalar_one()
    assert event.data["follow_up_of_number"] == 1 and event.data["number"] == 2


async def test_follow_up_prefers_previous_answering_agent(client_factory, db):
    asker, target_member, _o, _a, b, _c = await _world(client_factory, db)
    answerer = (await b.post("/api/agents", json={"program": "claude_code", "max_concurrent_runs": 2})).json()
    await b.put(f"/api/agents/{answerer['id']}/bindings",
                json={"bindings": [{"project_ref": "QBB", "local_path": "/repo"}]})
    agent_id = await _agent(db, asker)
    q1 = await _agent_ask(asker, agent_id)
    await db.execute(update(Question).where(Question.id == q1.id).values(
        status=QuestionStatus.answered, answer_md="Signed with HMAC", answered_by_agent_id=uuid.UUID(answerer["id"])))
    await db.commit()
    q2 = await _agent_ask(asker, agent_id, follow_up_to="QBB-Q1")
    assert q2.prefer_agent_id == uuid.UUID(answerer["id"]) and q2.prefer_only is False


async def test_follow_up_refused_for_other_task_or_project_or_unknown(client_factory, db):
    asker, _t, _o, a, _b, _c = await _world(client_factory, db)
    await _second_task(a)
    await make_project(client_factory(), db, "QCC", asker)
    agent_id = await _agent(db, asker)
    await _agent_ask(asker, agent_id)
    for kw in ({"task_key": "QAA-2", "follow_up_to": "QBB-Q1"},                 # another task's question
               {"project_key": "QCC", "follow_up_to": "QBB-Q1"},                # another project
               {"follow_up_to": "QBB-Q99"}, {"follow_up_to": "nonsense"}):      # unknown, malformed
        e = await _refused(_agent_ask(asker, agent_id, **kw))
        assert (e.status_code, e.detail) == (422, "invalid_follow_up"), kw


async def test_follow_up_across_chat_rounds_allowed(client_factory, db):
    asker, _t, _o, a, _b, _c = await _world(client_factory, db)
    await _second_task(a)
    await _chat_of_two_rounds(db, asker)
    agent_id = await _agent(db, asker)
    q1 = await _agent_ask(asker, agent_id, task_key="QAA-1")
    q2 = await _agent_ask(asker, agent_id, task_key="QAA-2", follow_up_to="QBB-Q1")
    assert q2.follow_up_of_id == q1.id


async def test_agent_ask_limit_twenty_per_chat(client_factory, db):
    asker, _t, _o, a, _b, _c = await _world(client_factory, db)
    await _second_task(a)
    await _chat_of_two_rounds(db, asker)
    agent_id = await _agent(db, asker)
    for i in range(20):
        await _agent_ask(asker, agent_id, task_key="QAA-1" if i < 10 else "QAA-2")
    e = await _refused(_agent_ask(asker, agent_id, task_key="QAA-2"))
    assert (e.status_code, e.detail) == (429, "question_limit")


async def test_person_asking_by_hand_not_limited_per_task(client_factory, db):
    asker, *_rest = await _world(client_factory, db)
    for _ in range(21):
        q = await _person_ask(asker)
        await db.execute(update(Question).where(Question.id == q.id).values(status=QuestionStatus.answered))
        await db.commit()


async def test_agent_questions_skip_per_user_cap(client_factory, db):
    asker, *_rest = await _world(client_factory, db)
    agent_id = await _agent(db, asker)
    for _ in range(20):
        await _agent_ask(asker, agent_id)
    async with SessionLocal() as s:
        assert await service.open_question_count(s, await s.get(User, asker.id)) == 0
    await _person_ask(asker)  # a person still asks: the agent's questions don't fill their cap
