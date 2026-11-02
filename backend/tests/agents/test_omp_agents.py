"""OMP (Oh My Pi) as a third agent program: sent only to runners that advertise omp/1."""

import json
import uuid

from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.hub.machines import machine_programs
from app.runner.registry import OMP_PROBLEM, registry
from tests.a2a.test_preference import _ask, _no_suggestions
from tests.a2a.test_routing import _cleanup, _world
from tests.agent_runs.test_dispatch import (
    _dispatch_in_own_session,
    _fake_conn,
    _FakeSocket,
    queue_run,
)
from tests.factories import login, make_project, make_user


async def _bound_agent(client, db, program):
    me = await make_user(db, name="Mo")
    await make_project(client, db, "OMP", me)
    await login(client, me)
    r = await client.post("/api/agents", json={"program": program})
    assert r.status_code == 201, r.text
    agent = r.json()
    r = await client.put(f"/api/agents/{agent['id']}/bindings",
                         json={"bindings": [{"project_ref": "OMP", "local_path": "/repo"}]})
    assert r.status_code == 200, r.text
    task = (await client.post("/api/projects/OMP/tasks", json={"title": "T", "assignee_agent_id": agent["id"]})).json()
    return me, agent, task


def _started(sock):
    return [f["run_id"] for f in map(json.loads, sock.sent) if f["type"] == "run_start"]


def _problems(agents, agent):
    return next(a for a in agents if a["id"] == agent["id"])["problems"]


async def test_omp_agent_defaults(client, db):
    me = await make_user(db, name="Mo")
    await login(client, me)
    r = await client.post("/api/agents", json={"program": "omp"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["program"] == "omp" and a["name"] == "Mo's OMP" and a["model"] is None


async def test_omp_run_waits_for_a_runner_with_omp(client, db):
    me, agent, task = await _bound_agent(client, db, "omp")
    run = await queue_run(task["key"])
    sock = _FakeSocket()
    conn = await _fake_conn(me, agent, sock)
    try:
        await _dispatch_in_own_session(me.id)
        assert _started(sock) == []
        assert OMP_PROBLEM in _problems((await client.get("/api/agents/mine")).json(), agent)
        conn.capabilities.add("omp/1")
        await _dispatch_in_own_session(me.id)
        assert _started(sock) == [run["id"]]
        assert OMP_PROBLEM not in _problems((await client.get("/api/agents/mine")).json(), agent)
    finally:
        registry._conns.pop(me.id, None)
    assert OMP_PROBLEM == "Update the runner to use OMP agents."


async def test_claude_agent_unaffected_by_omp_capability(client, db):
    me, agent, task = await _bound_agent(client, db, "claude_code")
    run = await queue_run(task["key"])
    sock = _FakeSocket()
    await _fake_conn(me, agent, sock)  # a current runner without omp/1
    try:
        await _dispatch_in_own_session(me.id)
        assert _started(sock) == [run["id"]]
        assert OMP_PROBLEM not in _problems((await client.get("/api/agents/mine")).json(), agent)
    finally:
        registry._conns.pop(me.id, None)
    rows = (await db.execute(select(AgentRun.status))).scalars().all()
    assert rows == ["running"]


async def test_hub_push_programs_include_omp_only_with_capability(client, db):
    me, omp_agent, _ = await _bound_agent(client, db, "omp")
    r = await client.post("/api/agents", json={"program": "claude_code", "runner_token_id": None})
    claude = r.json()
    conn = await _fake_conn(me, omp_agent, _FakeSocket())
    registry._conns[conn.token_id] = conn  # as the hub looks machines up: by token
    try:
        await client.patch(f"/api/agents/{claude['id']}", json={"runner_token_id": str(conn.token_id)})
        assert await machine_programs(db, conn.token_id) == ["claude_code"]
        conn.capabilities.add("omp/1")
        assert await machine_programs(db, conn.token_id) == ["claude_code", "omp"]
        registry._conns.pop(me.id, None)  # offline: the push waits, and is built again when the runner is back
        registry._conns.pop(conn.token_id, None)
        assert await machine_programs(db, conn.token_id) == ["claude_code", "omp"]
    finally:
        registry._conns.pop(me.id, None)
        registry._conns.pop(conn.token_id, None)


async def test_question_prefers_omp_program(client, db, monkeypatch):
    monkeypatch.setattr("app.a2a.service.suggest", _no_suggestions)
    m1, m2, asker = await _world(client, db)
    await login(client, m1)
    agent = (await client.post("/api/agents", json={"program": "omp", "name": f"omp-{uuid.uuid4().hex[:6]}"})).json()
    await client.put(f"/api/agents/{agent['id']}/bindings",
                     json={"bindings": [{"project_ref": "QBB", "local_path": "/repo/qbb"}]})
    try:
        q = await _ask(client, asker, prefer_program="omp")
        assert q["preference"] == {"program": "omp", "agent": None, "if_busy": "wait"}
    finally:
        _cleanup(m1, m2)
