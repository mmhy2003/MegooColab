import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.a2a.models import Question, QuestionStatus
from app.agent_runs.models import AgentRun
from app.agent_runs.service import _claim_next, apply_update
from app.core.db import SessionLocal
from app.mcp_server.auth import current_run, require_run_task
from app.runner.registry import WORKFLOW_CAPABILITY, registry
from app.tasks.models import TaskEvent
from tests.agent_runs.test_dispatch import _fake_conn, _FakeSocket
from tests.factories import login, make_project, make_user


async def _world(client, db):
    me = await make_user(db)
    project, _, _ = await make_project(client, db, "PAY", me)
    await make_project(client, db, "OPS", me)
    await login(client, me)
    agent = (await client.post("/api/agents", json={"program": "claude_code", "max_concurrent_runs": 3})).json()
    await client.put(f"/api/agents/{agent['id']}/bindings",
                     json={"bindings": [{"project_ref": "PAY", "local_path": "/repo"}]})
    return me, uuid.UUID(project["id"]), agent


async def _question(db, project_id, me, number=1):
    q = Question(target_project_id=project_id, number=number, asked_by_user_id=me.id, title="How?", body="How?")
    db.add(q)
    await db.commit()
    return q


def _question_run(q, agent, me, **kw):
    return AgentRun(question_id=q.id, agent_id=uuid.UUID(agent["id"]), requested_by=me.id, policy="read_only",
                    prompt="p", **kw)


async def test_run_needs_exactly_one_target(client, db):
    me, pid, agent = await _world(client, db)
    q = await _question(db, pid, me)
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "t"})).json()
    base = {"agent_id": uuid.UUID(agent["id"]), "requested_by": me.id, "policy": "read_only", "prompt": "p"}
    for targets in ({}, {"question_id": q.id, "task_id": uuid.UUID(task["id"])}):
        async with SessionLocal() as s:
            s.add(AgentRun(**base, **targets))
            with pytest.raises(IntegrityError):
                await s.commit()


async def test_question_numbers_per_project(client, db):
    me, pid, _agent = await _world(client, db)
    ops = (await client.get("/api/projects/OPS")).json()
    a = await _question(db, pid, me, 1)
    b = await _question(db, uuid.UUID(ops["id"]), me, 1)
    assert (a.number, b.number, a.status) == (1, 1, QuestionStatus.queued)
    db.add(Question(target_project_id=pid, number=1, asked_by_user_id=me.id, title="x", body="x"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_question_run_claim_one_active_per_question(client, db):
    me, pid, agent = await _world(client, db)
    q = await _question(db, pid, me)
    db.add_all([_question_run(q, agent, me), _question_run(q, agent, me)])
    await db.commit()
    conn = _fake_conn(me, agent, _FakeSocket())
    conn.capabilities.add(WORKFLOW_CAPABILITY)
    try:
        async with SessionLocal() as s:
            first = await _claim_next(s, uuid.UUID(agent["id"]), me.id)
        async with SessionLocal() as s:
            second = await _claim_next(s, uuid.UUID(agent["id"]), me.id)
        assert first is not None and second is None
    finally:
        registry._conns.pop(me.id, None)


async def test_question_run_not_claimed_on_v1_runner(client, db):
    me, pid, agent = await _world(client, db)
    q = await _question(db, pid, me)
    db.add(_question_run(q, agent, me))
    await db.commit()
    _fake_conn(me, agent, _FakeSocket())  # no workflow/1 capability
    try:
        async with SessionLocal() as s:
            assert await _claim_next(s, uuid.UUID(agent["id"]), me.id) is None
    finally:
        registry._conns.pop(me.id, None)


async def test_question_run_updates_ignored(client, db):
    me, pid, agent = await _world(client, db)
    q = await _question(db, pid, me)
    run = _question_run(q, agent, me, status="running")
    db.add(run)
    await db.commit()
    async with SessionLocal() as s:
        await apply_update(s, me.id, run.id, 1, "message", {"text": "reading the code"})
        await s.commit()
    await db.refresh(run)
    assert run.last_seq == 1
    assert (await db.execute(select(TaskEvent))).scalars().all() == [] or all(
        e.kind != "agent_message" for e in (await db.execute(select(TaskEvent))).scalars()
    )


async def test_require_run_task_refuses_question_runs(client, db):
    me, pid, agent = await _world(client, db)
    q = await _question(db, pid, me)
    run = _question_run(q, agent, me, status="running")
    db.add(run)
    await db.commit()
    token = current_run.set(run)
    try:
        from mcp.server.mcpserver.exceptions import ToolError

        with pytest.raises(ToolError, match="not_allowed_in_role"):
            await require_run_task(db, "PAY-1")
    finally:
        current_run.reset(token)
