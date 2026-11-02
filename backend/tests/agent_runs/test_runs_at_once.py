"""Runs at once: an agent works on up to max_concurrent_runs tasks and chats at the same time, and the owner can
raise or lower that any time."""

import json
import uuid

from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.runner.registry import registry
from tests.agent_runs.test_dispatch import (
    _avail,
    _dispatch_in_own_session,
    _fake_conn,
    _FakeSocket,
    _offline_runs,
    _setup,
    _start,
    _status_report,
    _task,
    _wait_run,
)
from tests.runner.test_runner_ws import URL, _hello, _manager_with_project


def _started(sock: _FakeSocket) -> list[str]:
    return [f["run_id"] for f in map(json.loads, sock.sent) if f["type"] == "run_start"]


def _mine(agents: list[dict], agent: dict) -> dict:
    return next(a for a in agents if a["id"] == agent["id"])


async def test_agent_is_busy_only_when_every_slot_is_taken(client, db):
    me, agent, runs = await _offline_runs(client, db, n=2, max_runs=2)
    sock = _FakeSocket()
    conn = await _fake_conn(me, agent, sock)
    try:
        conn.run_limits[uuid.UUID(agent["id"])] = 1  # as welcomed: one at a time
        await _dispatch_in_own_session(me.id)
        out = _mine((await client.get("/api/agents/mine")).json(), agent)
        assert out["status"] == "online" and out["running"] == 1  # one of two slots taken: still takes work
        task = (await client.get(f"/api/tasks/{runs[0]['task_key']}")).json()
        assert task["assignee_agent"]["status"] == "online"
        # the dashboard still counts it as working
        dash = (await client.get("/api/dashboard", params={"scope": "mine"})).json()
        assert _mine(dash["agents"], agent)["status"] == "busy"

        conn.run_limits[uuid.UUID(agent["id"])] = 2
        await _dispatch_in_own_session(me.id)
        out = _mine((await client.get("/api/agents/mine")).json(), agent)
        assert out["status"] == "busy" and out["running"] == 2
    finally:
        registry._conns.pop(me.id, None)


async def test_dispatch_never_exceeds_the_limit_the_runner_was_welcomed_with(client, db):
    """Raised but not yet welcomed: a second run_start would reach a runner that still allows one, which
    would fail it as busy."""
    me, agent, runs = await _offline_runs(client, db, n=2, max_runs=2)
    sock = _FakeSocket()
    conn = await _fake_conn(me, agent, sock)
    conn.run_limits[uuid.UUID(agent["id"])] = 1
    try:
        await _dispatch_in_own_session(me.id)
    finally:
        registry._conns.pop(me.id, None)
    assert _started(sock) == [runs[0]["id"]]
    rows = (await db.execute(select(AgentRun.status).order_by(AgentRun.created_at))).scalars().all()
    assert rows == ["running", "queued"]


async def test_lowering_runs_at_once_keeps_running_runs_and_holds_new_ones(client, db):
    me, agent, runs = await _offline_runs(client, db, n=3, max_runs=2)
    sock = _FakeSocket()
    await _fake_conn(me, agent, sock)
    try:
        await _dispatch_in_own_session(me.id)
        r = await client.patch(f"/api/agents/{agent['id']}", json={"max_concurrent_runs": 1})
        assert r.status_code == 200, r.text
        assert r.json()["max_concurrent_runs"] == 1 and r.json()["running"] == 2 and r.json()["status"] == "busy"
        await _dispatch_in_own_session(me.id)
    finally:
        registry._conns.pop(me.id, None)
    assert _started(sock) == [runs[0]["id"], runs[1]["id"]]
    rows = (await db.execute(select(AgentRun.status).order_by(AgentRun.created_at))).scalars().all()
    assert rows == ["running", "running", "queued"]


async def test_raising_runs_at_once_starts_waiting_work_after_the_new_welcome(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, first = _setup(tc, title="First")
    second = _task(tc, agent, title="Second")
    run1 = _start(tc, first)
    run2 = _start(tc, second)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        assert ws.receive_json()["type"] == "welcome"
        ws.send_json(_hello([_avail(agent)]))
        ws.send_json(_status_report(agent))
        msg = ws.receive_json()
        assert msg["type"] == "run_start" and msg["run_id"] == run1["id"]
        _wait_run(tc, first, run1["id"], "running")

        r = tc.patch(f"/api/agents/{agent['id']}", json={"max_concurrent_runs": 2})
        assert r.status_code == 200, r.text
        seen = []
        while True:
            msg = ws.receive_json()
            seen.append(msg["type"])
            if msg["type"] == "welcome":
                assert msg["agents"][0]["max_concurrent_runs"] == 2
            if msg["type"] == "run_start":
                assert msg["run_id"] == run2["id"]
                break
        assert seen.index("welcome") < seen.index("run_start")  # the runner knows the new limit first
        _wait_run(tc, second, run2["id"], "running")
