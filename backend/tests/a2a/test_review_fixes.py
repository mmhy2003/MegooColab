"""Final-review fixes for agent-to-agent questions (Plan 6)."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.a2a import routing, service
from app.a2a.models import Question, QuestionStatus
from app.agent_runs.models import AgentRun
from app.agent_runs.service import finish_run
from app.audit.models import AuditLog
from app.core.db import SessionLocal
from app.runner import router as runner_router
from app.runner.protocol import runner_message
from app.runner.registry import WORKFLOW_CAPABILITY, registry
from app.workflow import engine
from tests.a2a.test_ask import _ask
from tests.a2a.test_ask import _world as _ask_world
from tests.a2a.test_routing import _agent, _cleanup, _question, _runs, _world
from tests.agent_runs.test_dispatch import _fake_conn, _FakeSocket
from tests.factories import login, make_user


async def _conn(user, agent):
    sock = _FakeSocket()
    conn = await _fake_conn(user, agent, sock)
    conn.capabilities.add(WORKFLOW_CAPABILITY)
    return conn, sock


def _starts(sock) -> list[dict]:
    return [m for m in map(json.loads, sock.sent) if m["type"] == "run_start"]


async def _q(qid) -> Question:
    async with SessionLocal() as s:
        return await s.get(Question, qid)


async def _set_running(run_id) -> None:
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run_id).values(status="running"))
        await s.commit()


# -- a runner disappears: the question moves to another agent, and that agent is actually started ----------


async def test_runner_disconnect_mid_answer_starts_the_next_agent(client, db):
    m1, m2, asker = await _world(client, db)
    a1, a2 = await _agent(client, m1), await _agent(client, m2)
    conn1, sock1 = await _conn(m1, a1)
    try:
        async with SessionLocal() as s:
            user = await s.get(type(asker), asker.id)
            q, _ = await service.ask(s, user, project_key="QBB", body="Where is the retry policy?")
            await engine.dispatch_queued(s)
        assert len(_starts(sock1)) == 1
        _conn2, sock2 = await _conn(m2, a2)
        registry._conns.pop(m1.id, None)  # m1's laptop sleeps
        await runner_router._fail_runs(conn1)
        assert len(_starts(sock2)) == 1, "the rerouted run was never sent"
        active = [r for r in await _runs(db, q.id) if r.status in ("queued", "running")]
        assert [(str(r.agent_id), r.status) for r in active] == [(a2["id"], "running")]
    finally:
        _cleanup(m1, m2)


async def test_queued_answer_run_of_connected_owner_is_dispatched_by_the_loop(client, db):
    m1, _m2, asker = await _world(client, db)
    a1 = await _agent(client, m1)
    _conn1, sock1 = await _conn(m1, a1)
    try:
        qid = await _question(db, asker)  # routed and queued, never dispatched (no dispatch_queued)
        assert [r.status for r in await _runs(db, qid)] == ["queued"]
        await routing.route_and_dispatch()
        assert len(_starts(sock1)) == 1
    finally:
        _cleanup(m1)


async def test_answer_run_queued_on_an_agent_gone_offline_is_released(client, db):
    m1, m2, asker = await _world(client, db)
    a1, a2 = await _agent(client, m1), await _agent(client, m2)
    await _conn(m1, a1)
    try:
        qid = await _question(db, asker)
        [stale] = await _runs(db, qid)
        registry._conns.pop(m1.id, None)  # gone before the run was sent
        async with SessionLocal() as s:
            await s.execute(update(AgentRun).where(AgentRun.id == stale.id)
                            .values(created_at=datetime.now(UTC) - timedelta(minutes=10)))
            await s.commit()
        _conn2, sock2 = await _conn(m2, a2)
        await routing.route_and_dispatch()
        runs = {str(r.agent_id): r.status for r in await _runs(db, qid)}
        assert runs == {a1["id"]: "cancelled", a2["id"]: "running"} and len(_starts(sock2)) == 1
        assert a1["id"] in (await _q(qid)).tried_agent_ids
    finally:
        _cleanup(m1, m2)


# -- nobody else can answer: a human is asked instead of "waiting for a runner" forever --------------------


async def test_only_agent_failing_moves_question_to_needs_human(client, db):
    m1, _m2, asker = await _world(client, db)
    a1 = await _agent(client, m1)
    await _conn(m1, a1)
    try:
        qid = await _question(db, asker)
        [run] = await _runs(db, qid)
        await _set_running(run.id)
        async with SessionLocal() as s:
            await finish_run(s, m1.id, run.id, "failed", "", "agent_error")
        q = await _q(qid)
        assert (q.status, q.attempts) == (QuestionStatus.needs_human, 1)
    finally:
        _cleanup(m1)


async def test_no_bound_agent_at_all_still_waits_queued(client, db):
    _m1, _m2, asker = await _world(client, db)
    qid = await _question(db, asker)
    async with SessionLocal() as s:
        await routing.route_question(s, qid)
        await s.commit()
    assert (await _q(qid)).status == QuestionStatus.queued


async def test_rejecting_the_only_agents_draft_asks_a_human(client, db):
    m1, _m2, asker = await _world(client, db)
    a1 = await _agent(client, m1)
    await _conn(m1, a1)
    try:
        qid = await _question(db, asker)
        [run] = await _runs(db, qid)
        await _set_running(run.id)
        async with SessionLocal() as s:
            await service.submit(s, await s.get(AgentRun, run.id), "A draft", [])
            await s.commit()
        async with SessionLocal() as s:
            owner = await s.get(type(m1), m1.id)
            await service.reject(s, owner, await s.get(Question, qid), reason="Wrong file")
            await s.commit()
        q = await _q(qid)
        assert q.status == QuestionStatus.needs_human and q.redacted is False
    finally:
        _cleanup(m1)


# -- lock order: a human withdrawing while the run ends must not deadlock -----------------------------------


async def test_withdraw_while_run_finishes_does_not_deadlock(client, db):
    m1, _m2, asker = await _world(client, db)
    a1 = await _agent(client, m1)
    await _conn(m1, a1)
    try:
        qid = await _question(db, asker)
        [run] = await _runs(db, qid)
    finally:
        _cleanup(m1)  # offline: the withdrawal cancels the run itself
    await _set_running(run.id)
    async with SessionLocal() as a:
        user = await a.get(type(asker), asker.id)
        locked = await service.lock_question(a, qid)

        async def runner_reports_end():
            async with SessionLocal() as b:
                await finish_run(b, m1.id, run.id, "completed", "done", None)

        ending = asyncio.create_task(runner_reports_end())
        await asyncio.sleep(0.5)  # the run's end now waits for the question (wrongly: holds the run first)
        await service.withdraw(a, user, locked)
        await a.commit()
    await asyncio.wait_for(ending, 10)  # no DeadlockDetectedError
    async with SessionLocal() as s:
        assert (await s.get(AgentRun, run.id)).status == "cancelled"


# -- MCP and REST share the length caps ---------------------------------------------------------------------


async def test_ask_service_caps_body_and_context(client, db):
    _m1, _m2, asker = await _world(client, db)
    async with SessionLocal() as s:
        user = await s.get(type(asker), asker.id)
        for kw in ({"body": "x" * 4001}, {"body": "ok", "context": "y" * 8001}):
            with pytest.raises(HTTPException) as e:
                await service.ask(s, user, project_key="QBB", **kw)
            assert (e.value.status_code, e.value.detail) == (422, "too_large")


# -- the asking side finds earlier answers it can read ------------------------------------------------------


async def test_answered_question_suggested_to_readers_on_the_asking_side(client_factory, db):
    _asker, _target_member, _outsider, a, b, c = await _ask_world(client_factory, db)
    q = (await _ask(a, body="How are orders webhooks signed?", task_key="QAA-1")).json()["question"]
    await b.post(f"/api/questions/{q['id']}/answer", json={"answer_md": "HMAC SHA256 over the body."})
    from app.teams.models import TeamMember

    teammate = await make_user(db)
    team_id = (await a.get("/api/projects/QAA")).json()["team_ids"][0]
    db.add(TeamMember(team_id=uuid.UUID(team_id), user_id=teammate.id))
    await db.commit()
    t = client_factory()
    await login(t, teammate)
    body = {"project_key": "QBB", "body": "How are orders webhooks signed?"}
    found = (await t.post("/api/questions/suggest", json=body)).json()
    hit = next(s for s in found if s["kind"] == "question")
    assert (hit["id"], hit["link"]) == (q["id"], f"/questions/{q['id']}")
    assert hit["title"] == "QBB-Q1: How are orders webhooks signed?" and "HMAC" in hit["snippet"]
    assert all(s["kind"] != "question" for s in (await c.post("/api/questions/suggest", json=body)).json())


# -- R1: an answering session that changed the repository ---------------------------------------------------


async def test_answer_run_that_changed_the_repository_loses_its_draft(client, db):
    m1, m2, asker = await _world(client, db)
    a1 = await _agent(client, m1)
    await _agent(client, m2)  # bound, offline: the question waits for it
    await _conn(m1, a1)
    try:
        qid = await _question(db, asker)
        [run] = await _runs(db, qid)
    finally:
        _cleanup(m1)
    await _set_running(run.id)
    async with SessionLocal() as s:
        await service.submit(s, await s.get(AgentRun, run.id), "A draft", [])
        await s.commit()
    msg = runner_message.validate_python({
        "type": "run_finished", "run_id": str(run.id), "outcome": "completed", "summary": "",
        "git_before": {"head": "a" * 40, "branch": "megoo/QBB-Q1", "dirty": False},
        "git_after": {"head": "b" * 40, "branch": "megoo/QBB-Q1", "dirty": False},
    })
    async with SessionLocal() as s:
        await finish_run(s, m1.id, run.id, "completed", "", None, msg)
    q = await _q(qid)
    assert (q.draft_md, q.status) == (None, QuestionStatus.queued) and a1["id"] in q.tried_agent_ids
    audits = await db.execute(select(AuditLog).where(AuditLog.action == "a2a.answer.enforcement_violation"))
    assert len(audits.scalars().all()) == 1
