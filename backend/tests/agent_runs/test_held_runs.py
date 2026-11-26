"""The runs a dropped runner held: claimed by runs_held, failed when the grace period runs out (MC-214)."""

import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun
from app.agent_runs.service import claim_held_runs, fail_disconnected_runs, fail_held_runs, running_runs_by_token
from app.agents.models import Agent
from app.auth.models import TokenScope, User
from app.auth.tokens import create_token
from app.core.db import SessionLocal
from app.notifications.models import Kind, Notification
from app.runner.registry import RunnerConn, registry
from tests.agent_runs.test_dispatch import _fake_conn, _FakeSocket
from tests.agent_runs.test_updates import _row, _running


async def _set(run_id, **values):
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run_id).values(**values))
        await s.commit()


async def test_claim_held_runs_claims_running_runs_of_the_machine(client, db):
    me, agent, [a, done, b] = await _running(client, db, n=3)
    conn = await _fake_conn(me, agent, _FakeSocket())
    try:
        await _set(done, status="completed")
        stray = uuid.uuid4()
        async with SessionLocal() as s:
            others = await claim_held_runs(s, conn, [a, done, stray, b])
        assert others == [done, stray]
        assert conn.run_ids == {a, b}
    finally:
        registry._conns.pop(me.id, None)


async def test_fail_held_runs_ends_runs_no_connection_holds(client, db):
    me, agent, [a, b, c] = await _running(client, db, n=3)
    conn = await _fake_conn(me, agent, _FakeSocket())
    try:
        await _set(b, cancelled_by=me.id)
        conn.run_ids.add(c)  # a live connection holds c
        async with SessionLocal() as s:
            await fail_held_runs(s, conn.token_id, me.id, set())
            await s.commit()
        row_a = await _row(db, a)
        assert (row_a.status, row_a.reason) == ("failed", "runner_disconnected")
        assert (await _row(db, b)).status == "cancelled"
        assert (await _row(db, c)).status == "running"
        kinds = (await db.execute(select(Notification.kind))).scalars().all()
        assert Kind.agent_offline in kinds
    finally:
        registry._conns.pop(me.id, None)


async def test_fail_held_runs_counts_remembered_runs_after_an_unlink(client, db):
    me, agent, [a] = await _running(client, db)
    conn = await _fake_conn(me, agent, _FakeSocket())
    registry._conns.pop(me.id, None)
    try:
        async with SessionLocal() as s:
            await s.execute(update(Agent).where(Agent.id == uuid.UUID(agent["id"])).values(runner_token_id=None))
            await s.commit()
        async with SessionLocal() as s:
            await fail_held_runs(s, conn.token_id, me.id, {a})
            await s.commit()
        assert (await _row(db, a)).status == "failed"
    finally:
        registry._conns.pop(me.id, None)


async def test_fail_disconnected_runs_skips_a_run_a_live_connection_holds(client, db):
    me, agent, [a] = await _running(client, db)
    old = await _fake_conn(me, agent, _FakeSocket())
    old.run_ids.add(a)
    old.closed.set()
    live = RunnerConn(old.token_id, me.id, _FakeSocket())
    live.run_ids.add(a)  # the runner came back and claimed it
    registry._conns[old.token_id] = live
    try:
        async with SessionLocal() as s:
            await fail_disconnected_runs(s, old)
            await s.commit()
        assert (await _row(db, a)).status == "running"
    finally:
        registry._conns.pop(me.id, None)
        registry._conns.pop(old.token_id, None)


async def test_running_runs_by_token_groups_by_token_and_owner(client, db):
    me, agent, [a, b, done, unlinked] = await _running(client, db, n=4)
    conn = await _fake_conn(me, agent, _FakeSocket())
    registry._conns.pop(me.id, None)
    async with SessionLocal() as s:
        other, _ = await create_token(s, await s.get(User, me.id), "other machine", [TokenScope.runner], None)
        second = Agent(owner_id=me.id, name="second", program="claude_code", runner_token_id=other.id)
        loose = Agent(owner_id=me.id, name="loose", program="claude_code")
        s.add_all([second, loose])
        await s.flush()
        await s.execute(update(AgentRun).where(AgentRun.id == b).values(agent_id=second.id))
        await s.execute(update(AgentRun).where(AgentRun.id == unlinked).values(agent_id=loose.id))
        await s.execute(update(AgentRun).where(AgentRun.id == done).values(status="completed"))
        await s.commit()
        other_id = other.id
    async with SessionLocal() as s:
        assert await running_runs_by_token(s) == {(conn.token_id, me.id): {a}, (other_id, me.id): {b}}
