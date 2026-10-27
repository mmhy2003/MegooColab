"""ADM-2: agent sessions are audited when sent and when they end. ADM-3: answering runs in the admin overview;
an answering run can be cancelled by its agent's owner or an admin."""

import uuid

from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.agent_runs.service import finish_run
from app.audit.models import AuditLog
from app.auth.models import Role
from app.core.db import SessionLocal
from app.runner.registry import registry
from app.workflow import engine
from tests.a2a.test_routing import _agent, _cleanup, _online, _world
from tests.agent_runs.test_dispatch import (
    _dispatch_in_own_session,
    _fake_conn,
    _FakeSocket,
    _offline_runs,
)
from tests.factories import login, make_user


async def _audits(action: str) -> list[AuditLog]:
    async with SessionLocal() as s:
        return list((await s.execute(select(AuditLog).where(AuditLog.action == action)
                                      .order_by(AuditLog.created_at))).scalars())


async def _ask(asker, body="Where is the retry policy?"):
    from app.a2a import service

    async with SessionLocal() as s:
        user = await s.get(type(asker), asker.id)
        q, _ = await service.ask(s, user, project_key="QBB", body=body)
        await engine.dispatch_queued(s)
        return q.id


async def test_agent_run_start_and_end_audited(client, db):
    me, agent, [queued] = await _offline_runs(client, db)
    _fake_conn(me, agent, _FakeSocket())
    try:
        await _dispatch_in_own_session(me.id)
    finally:
        registry._conns.pop(me.id, None)
    [started] = await _audits("agent_run.started")
    assert (started.target_type, str(started.target_id)) == ("agent_run", queued["id"])
    assert started.data["agent_id"] == agent["id"] and started.data["task_id"] and started.data["role"] is None
    async with SessionLocal() as s:
        await finish_run(s, me.id, uuid.UUID(queued["id"]), "failed", "", "agent_error")
    [ended] = await _audits("agent_run.ended")
    assert ended.data == {"status": "failed", "reason": "agent_error"} and str(ended.target_id) == queued["id"]


async def test_answering_run_audited(client, db):
    m1, _m2, asker = await _world(client, db)
    a1 = await _agent(client, m1)
    _online(m1, a1)
    try:
        qid = await _ask(asker)
    finally:
        _cleanup(m1)
    [started] = await _audits("agent_run.started")
    assert started.data["question_id"] == str(qid) and started.data["role"] == "answer"


async def test_cancel_answering_run_by_owner_or_admin(client, client_factory, db):
    m1, m2, asker = await _world(client, db)
    a1 = await _agent(client, m1)
    _online(m1, a1)
    try:
        qid = await _ask(asker)
    finally:
        _cleanup(m1)  # offline: a cancel ends the run at once
    run = (await db.execute(select(AgentRun).where(AgentRun.question_id == qid))).scalar_one()
    other = client_factory()
    await login(other, m2)
    r = await other.post(f"/api/agent-runs/{run.id}/cancel")
    assert (r.status_code, r.json()["detail"]) == (403, "cannot_use_agent")
    owner = client_factory()
    await login(owner, m1)
    r = await owner.post(f"/api/agent-runs/{run.id}/cancel")
    assert r.status_code == 204, r.text
    await db.refresh(run)
    assert run.status == "cancelled"
    qid2 = None
    _online(m1, a1)
    try:
        qid2 = await _ask(asker, body="And the backoff?")
    finally:
        _cleanup(m1)
    admin = client_factory()
    await login(admin, await make_user(db, role=Role.admin))
    run2 = (await db.execute(select(AgentRun).where(AgentRun.question_id == qid2))).scalar_one()
    assert (await admin.post(f"/api/agent-runs/{run2.id}/cancel")).status_code == 204


async def test_admin_agents_shows_answering_run(client, client_factory, db):
    m1, _m2, asker = await _world(client, db)
    a1 = await _agent(client, m1)
    _online(m1, a1)
    try:
        await _ask(asker)
        admin = client_factory()
        await login(admin, await make_user(db, role=Role.admin))
        rows = (await admin.get("/api/admin/agents")).json()
    finally:
        _cleanup(m1)
    [row] = [r for r in rows if r["id"] == a1["id"]]
    assert row["current_run"]["kind"] == "question" and row["current_run"]["task_key"] == "QBB-Q1"
