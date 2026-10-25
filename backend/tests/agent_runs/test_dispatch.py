"""Agent runs: start, queue, dispatch. Socket tests follow tests/runner/test_runner_ws.py."""

import asyncio
import json
import time
import uuid

import pytest
from sqlalchemy import select, update
from starlette.websockets import WebSocketDisconnect

from app.agent_runs.models import AgentRun
from app.agent_runs.service import _claim_next, _send_start, dispatch_pending, runs_out
from app.agents.models import Agent
from app.auth.models import Role
from app.core.db import SessionLocal
from app.projects.models import Project
from app.runner.registry import RunnerClosed, RunnerConn, registry
from app.tasks.models import Task, TaskEvent
from app.tasks.service import record_event
from app.workflow import methodology
from tests.factories import login, make_project, make_user
from tests.runner.test_runner_ws import (
    URL,
    _agent,
    _hello,
    _login,
    _manager_with_project,
    _mint,
    _wait_status,
)


def _setup(tc, ref="PAY", title="Fix login"):
    """Runner-scoped token, a bound agent, and a task assigned to it. Caller is the project manager."""
    token = _mint(tc)
    agent = _agent(tc)
    r = tc.put(
        f"/api/agents/{agent['id']}/bindings",
        json={"bindings": [{"project_ref": ref, "local_path": "/repo/pay"}]},
    )
    assert r.status_code == 200, r.text
    task = _task(tc, agent, title=title)
    return token, agent, task


def _task(tc, agent, ref="PAY", title="T", **body):
    r = tc.post(
        f"/api/projects/{ref}/tasks",
        json={"title": title, "assignee_agent_id": agent["id"], **body},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def queue_run(task_key: str, policy: str = "read_only", prompt: str | None = None) -> dict:
    """A plan-2 style run (no workflow role) on an agent-assigned task: queued, recorded, then dispatched, as
    the removed manual start endpoint did. Runs are otherwise started only by the workflow engine; these
    tests exercise the run queue and dispatch themselves."""
    project_key, number = task_key.split("-")
    async with SessionLocal() as s:
        task = (
            await s.execute(
                select(Task).join(Project, Project.id == Task.project_id)
                .where(Project.key == project_key, Task.number == int(number))
            )
        ).scalar_one()
        agent = await s.get(Agent, task.assignee_agent_id)
        run = AgentRun(
            task_id=task.id, agent_id=agent.id, requested_by=agent.owner_id, policy=policy, status="queued",
            prompt=prompt or f"Work on task {task_key}: {task.title}\n\n{task.description_md}",
        )
        s.add(run)
        await s.flush()
        await record_event(s, task, None, "agent_run_queued", {"run_id": str(run.id), "agent_id": str(agent.id)})
        await s.commit()
    async with SessionLocal() as s:
        await dispatch_pending(s, agent.owner_id)
        await s.commit()
    async with SessionLocal() as s:
        run = await s.get(AgentRun, run.id)
        return (await runs_out(s, [run]))[0].model_dump(mode="json")


def _start(tc, task, policy="read_only", prompt=None):
    """queue_run on the app's own event loop, where the runner sockets live."""
    return tc.portal.call(queue_run, task["key"], policy, prompt)


def _run_status(tc, task, run_id):
    runs = tc.get(f"/api/tasks/{task['key']}/agent-runs").json()
    return next(r["status"] for r in runs if r["id"] == run_id)


def _wait_run(tc, task, run_id, expected):
    deadline = time.monotonic() + 3
    while _run_status(tc, task, run_id) != expected:
        assert time.monotonic() < deadline, f"run stayed {_run_status(tc, task, run_id)}, wanted {expected}"
        time.sleep(0.02)


def _avail(agent):
    return {"agent_id": agent["id"], "available": True, "problems": []}


def _status_report(agent):
    return {"type": "agent_status", "agent_id": agent["id"], "available": True, "problems": []}


async def _event_kinds(db) -> list[str]:
    rows = await db.execute(select(TaskEvent.kind).order_by(TaskEvent.created_at))
    return [k for (k,) in rows.all()]


async def test_run_requires_agent_assignee_and_permission(client, client_factory, db):
    """Runs start only through the workflow (the manual start endpoint is gone); its start keeps the guards."""
    me = await make_user(db)
    other = await make_user(db)
    _, manager, _team = await make_project(client, db, "PAY", me, other)
    await methodology.seed_defaults(db)
    await db.commit()
    await login(client, me)
    agent = (await client.post("/api/agents", json={"program": "claude_code"})).json()
    await client.put(
        f"/api/agents/{agent['id']}/bindings",
        json={"bindings": [{"project_ref": "PAY", "local_path": "/repo"}]},
    )
    plain = (await client.post("/api/projects/PAY/tasks", json={"title": "No agent"})).json()
    r = await client.post(f"/api/tasks/{plain['key']}/workflow/start")
    assert r.status_code == 422 and r.json()["detail"] == "task_not_assigned_to_agent"

    t = (
        await client.post(
            "/api/projects/PAY/tasks",
            json={"title": "Fix login", "description_md": "Users cannot log in", "assignee_agent_id": agent["id"]},
        )
    ).json()

    oc = client_factory()
    await login(oc, other)
    r = await oc.post(f"/api/tasks/{t['key']}/workflow/start")
    assert r.status_code == 403 and r.json()["detail"] == "cannot_use_agent"

    r = await client.post(f"/api/tasks/{t['key']}/workflow/start")
    assert r.status_code == 200, r.text
    [run] = (await client.get(f"/api/tasks/{t['key']}/agent-runs")).json()
    assert run["status"] == "queued" and run["policy"] == "read_only" and run["task_key"] == t["key"]
    assert run["agent"] == {"id": agent["id"], "name": agent["name"], "program": "claude_code"}
    row = (await db.execute(select(AgentRun).where(AgentRun.id == uuid.UUID(run["id"])))).scalar_one()
    assert "Fix login\n\nUsers cannot log in" in row.prompt

    mc = client_factory()
    await login(mc, manager)
    r = await mc.post(f"/api/tasks/{t['key']}/workflow/start")
    assert r.status_code == 409 and r.json()["detail"] == "workflow_active"  # one active workflow (and run) per task
    assert (await client.post(f"/api/agent-runs/{run['id']}/cancel")).status_code == 204
    r = await mc.post(f"/api/tasks/{t['key']}/workflow/resume")
    assert r.status_code == 200, r.text
    listed = (await mc.get(f"/api/tasks/{t['key']}/agent-runs")).json()
    assert listed[1]["id"] == run["id"] and len(listed) == 2  # newest first
    assert "agent_run_queued" in await _event_kinds(db)


async def test_run_queued_while_runner_offline_then_dispatched_on_hello_exactly_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task, prompt="Do it")
    assert run["status"] == "queued" and run["started_at"] is None
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        assert ws.receive_json()["type"] == "welcome"
        for _ in range(2):  # two hellos in quick succession
            ws.send_json(_hello([_avail(agent)]))
        ws.send_json(_status_report(agent))
        assert ws.receive_json() == {
            "type": "run_start",
            "run_id": run["id"],
            "agent_id": agent["id"],
            "task": {"key": task["key"], "title": "Fix login", "description_md": "", "project_key": "PAY"},
            "local_path": "/repo/pay",
            "policy": "read_only",
            "prompt": "Do it",
        }
        _wait_run(tc, task, run["id"], "running")
        _wait_status(tc, agent["id"], "busy")
        # exactly one run_start: the next frame the runner sees is the cancel triggered now
        assert tc.post(f"/api/agent-runs/{run['id']}/cancel").status_code == 204
        assert ws.receive_json() == {"type": "run_cancel", "run_id": run["id"]}


class _FakeSocket:
    def __init__(self, fail=False):
        self.sent: list[str] = []
        self.fail = fail

    async def send_text(self, text):
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(text)

    async def close(self, code=1000):
        pass


async def _offline_runs(client, db, n=1, max_runs=1):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    agent = (
        await client.post("/api/agents", json={"program": "claude_code", "max_concurrent_runs": max_runs})
    ).json()
    await client.put(
        f"/api/agents/{agent['id']}/bindings",
        json={"bindings": [{"project_ref": "PAY", "local_path": "/repo"}]},
    )
    runs = []
    for i in range(n):
        body = {"title": f"T{i}", "assignee_agent_id": agent["id"]}
        t = (await client.post("/api/projects/PAY/tasks", json=body)).json()
        runs.append(await queue_run(t["key"]))
    return me, agent, runs


def _fake_conn(user, agent, socket):
    conn = RunnerConn(user.id, socket)
    conn.set_availability(uuid.UUID(agent["id"]), True, [])
    registry._conns[user.id] = conn
    return conn


async def _dispatch_in_own_session(owner_id):
    async with SessionLocal() as s:
        await dispatch_pending(s, owner_id)
        await s.commit()


async def test_concurrent_dispatch_sends_each_run_once(client, db):
    me, agent, runs = await _offline_runs(client, db, n=3, max_runs=2)
    sock = _FakeSocket()
    _fake_conn(me, agent, sock)
    try:
        await asyncio.gather(*[_dispatch_in_own_session(me.id) for _ in range(4)])
    finally:
        registry._conns.pop(me.id, None)
    started = [f["run_id"] for f in map(json.loads, sock.sent) if f["type"] == "run_start"]
    assert started == [runs[0]["id"], runs[1]["id"]]  # once each, oldest first, capped by max_concurrent_runs
    rows = (await db.execute(select(AgentRun.status))).scalars().all()
    assert sorted(rows) == ["queued", "running", "running"]


async def test_failed_send_leaves_run_queued(client, db):
    me, agent, _runs = await _offline_runs(client, db)
    _fake_conn(me, agent, _FakeSocket(fail=True))
    try:
        await _dispatch_in_own_session(me.id)
    finally:
        registry._conns.pop(me.id, None)
    row = (await db.execute(select(AgentRun))).scalar_one()
    assert row.status == "queued" and row.started_at is None


async def test_closed_connection_is_not_used(client, db):
    me, agent, _runs = await _offline_runs(client, db)
    sock = _FakeSocket()
    conn = _fake_conn(me, agent, sock)
    conn.closed.set()
    try:
        assert registry.conn_for_user(me.id) is None
        assert registry.available_agents(me.id) == set()
        await _dispatch_in_own_session(me.id)
        with pytest.raises(RunnerClosed):
            await conn.send({"type": "heartbeat"})
    finally:
        registry._conns.pop(me.id, None)
    assert sock.sent == []
    assert (await db.execute(select(AgentRun.status))).scalar_one() == "queued"


async def test_concurrency_limit_respected(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    second_task = _task(tc, agent, title="Second")
    first = _start(tc, task)
    second = _start(tc, second_task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert ws.receive_json()["run_id"] == first["id"]
        _wait_run(tc, task, first["id"], "running")
        ws.send_json(_status_report(agent))
        ws.send_json({"type": "heartbeat"})
        assert _run_status(tc, second_task, second["id"]) == "queued"
        # the first run ends (Task 6 does this on run_finished); the next report dispatches the second
        await db.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(first["id"])).values(status="completed"))
        await db.commit()
        ws.send_json(_status_report(agent))
        assert ws.receive_json()["run_id"] == second["id"]


async def test_disconnect_fails_running_runs(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert ws.receive_json()["type"] == "run_start"
        _wait_run(tc, task, run["id"], "running")
    _wait_run(tc, task, run["id"], "failed")
    out = tc.get(f"/api/tasks/{task['key']}/agent-runs").json()[0]
    assert out["reason"] == "runner_disconnected" and out["finished_at"] is not None
    kinds = await _event_kinds(db)
    assert "agent_run_started" in kinds and "agent_run_failed" in kinds
    _wait_status(tc, agent["id"], "offline")


async def test_cancel_queued_and_running(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    queued = _start(tc, task)
    assert tc.post(f"/api/agent-runs/{queued['id']}/cancel").status_code == 204
    assert _run_status(tc, task, queued["id"]) == "cancelled"
    again = tc.post(f"/api/agent-runs/{queued['id']}/cancel")
    assert again.status_code == 409 and again.json()["detail"] == "run_not_active"
    assert tc.post(f"/api/agent-runs/{uuid.uuid4()}/cancel").status_code == 404

    running = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert ws.receive_json()["run_id"] == running["id"]
        _wait_run(tc, task, running["id"], "running")
        assert tc.post(f"/api/agent-runs/{running['id']}/cancel").status_code == 204
        assert ws.receive_json() == {"type": "run_cancel", "run_id": running["id"]}
        # the runner is alive: the run stays running until its run_finished arrives (Task 6)
        assert _run_status(tc, task, running["id"]) == "running"

    _wait_run(tc, task, running["id"], "cancelled")  # the runner left before its run_finished: the user's cancel completes

    # runner gone and the row still marked running (e.g. after a server restart): cancel is immediate
    orphan = _start(tc, task)
    await db.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(orphan["id"])).values(status="running"))
    await db.commit()
    assert tc.post(f"/api/agent-runs/{orphan['id']}/cancel").status_code == 204
    assert _run_status(tc, task, orphan["id"]) == "cancelled"


async def test_deactivation_cancels_runs(db, tc_factory):
    tc, ac = tc_factory(lifespan=True), tc_factory()
    admin = await make_user(db, role=Role.admin)
    _login(ac, admin)
    me, _ = await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    running = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert ws.receive_json()["run_id"] == running["id"]
        _wait_run(tc, task, running["id"], "running")
        queued = _start(tc, _task(tc, agent, title="Second"))
        assert ac.post(f"/api/admin/users/{me.id}/deactivate").status_code == 204
        seen = []
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                seen.append(ws.receive_json())
        assert exc.value.code == 4401
        assert {"type": "run_cancel", "run_id": running["id"]} in seen
    rows = {str(r.id): r.status for r in (await db.execute(select(AgentRun))).scalars()}
    assert rows == {running["id"]: "cancelled", queued["id"]: "cancelled"}


async def test_delete_agent_with_active_runs_409_and_current_run(client, client_factory, db):
    _me, agent, runs = await _offline_runs(client, db)
    r = await client.delete(f"/api/agents/{agent['id']}")
    assert r.status_code == 409 and r.json()["detail"] == "agent_has_active_runs"
    admin = await make_user(db, role=Role.admin)
    ac = client_factory()
    await login(ac, admin)
    assert (await ac.get("/api/admin/agents")).json()[0]["current_run"] is None  # queued, not running
    await db.execute(update(AgentRun).values(status="running"))
    await db.commit()
    row = (await ac.get("/api/admin/agents")).json()[0]
    assert row["status"] == "busy"
    assert row["current_run"]["id"] == runs[0]["id"] and row["current_run"]["status"] == "running"
    assert row["current_run"]["task_key"].startswith("PAY-")
    await db.execute(update(AgentRun).values(status="completed"))
    await db.commit()
    assert (await client.delete(f"/api/agents/{agent['id']}")).status_code == 204


async def test_start_run_with_runner_online_sends_one_run_start_and_is_running(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        _wait_status(tc, agent["id"], "online")
        run = _start(tc, task, prompt="Go")
        assert run["status"] == "running" and run["started_at"] is not None
        assert ws.receive_json()["run_id"] == run["id"]
        # more reports must not start it again; the next frame is the cancel triggered now
        ws.send_json(_hello([_avail(agent)]))
        ws.send_json(_status_report(agent))
        ws.send_json({"type": "heartbeat"})
        assert tc.post(f"/api/agent-runs/{run['id']}/cancel").status_code == 204
        assert ws.receive_json() == {"type": "run_cancel", "run_id": run["id"]}


async def test_token_revocation_cancels_running_runs_as_runner_unauthorized(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert ws.receive_json()["run_id"] == run["id"]
        _wait_run(tc, task, run["id"], "running")
        assert tc.delete(f"/api/tokens/{token['id']}").status_code == 204
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                ws.receive_json()
        assert exc.value.code == 4401
    _wait_run(tc, task, run["id"], "cancelled")
    assert tc.get(f"/api/tasks/{task['key']}/agent-runs").json()[0]["reason"] == "runner_unauthorized"


# ---- cancel racing the dispatch (final review I2) ---------------------------


async def _claim(owner, agent):
    s = SessionLocal()
    run = await _claim_next(s, uuid.UUID(agent["id"]), owner.id)
    assert run is not None and run.status == "running"
    return s, run


async def test_cancel_between_claim_and_send_never_starts_the_run(client, db):
    me, agent, _runs = await _offline_runs(client, db)
    sock = _FakeSocket()
    conn = _fake_conn(me, agent, sock)
    try:
        s, run = await _claim(me, agent)
        async with s:
            # the cancel lands after the claim committed `running`, before run_start is sent
            assert (await client.post(f"/api/agent-runs/{run.id}/cancel")).status_code == 204
            assert await _send_start(s, conn, uuid.UUID(agent["id"]), run)
    finally:
        registry._conns.pop(me.id, None)
    assert sock.sent == []
    assert run.id not in conn.run_ids
    row = (await db.execute(select(AgentRun).execution_options(populate_existing=True))).scalar_one()
    assert row.status == "cancelled" and row.reason is None


async def test_unbound_check_does_not_overwrite_a_cancel(client, db):
    me, agent, _runs = await _offline_runs(client, db)
    sock = _FakeSocket()
    conn = _fake_conn(me, agent, sock)
    try:
        s, run = await _claim(me, agent)
        async with s:
            assert (await client.post(f"/api/agent-runs/{run.id}/cancel")).status_code == 204
            r = await client.put(f"/api/agents/{agent['id']}/bindings", json={"bindings": []})
            assert r.status_code == 200
            assert await _send_start(s, conn, uuid.UUID(agent["id"]), run)
    finally:
        registry._conns.pop(me.id, None)
    assert sock.sent == []
    row = (await db.execute(select(AgentRun).execution_options(populate_existing=True))).scalar_one()
    assert row.status == "cancelled" and row.reason is None
    assert "agent_run_failed" not in await _event_kinds(db)


class _GatedSocket(_FakeSocket):
    """Holds run_start in flight until the gate opens."""

    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()

    async def send_text(self, text):
        if json.loads(text)["type"] == "run_start":
            self.entered.set()
            await self.gate.wait()
        self.sent.append(text)


async def test_cancel_during_send_waits_and_follows_run_start(client, db):
    me, agent, runs = await _offline_runs(client, db)
    sock = _GatedSocket()
    _fake_conn(me, agent, sock)
    dispatch = asyncio.create_task(_dispatch_in_own_session(me.id))
    cancel = None
    try:
        await asyncio.wait_for(sock.entered.wait(), 5)
        cancel = asyncio.create_task(client.post(f"/api/agent-runs/{runs[0]['id']}/cancel"))
        await asyncio.sleep(0.3)
        cancelled_early = cancel.done()
        sock.gate.set()
        await asyncio.wait_for(dispatch, 5)
        assert (await asyncio.wait_for(cancel, 5)).status_code == 204
        assert not cancelled_early  # serialised behind the in-flight run_start
    finally:
        sock.gate.set()  # never leave a transaction open behind the test
        await asyncio.gather(dispatch, *([cancel] if cancel else []), return_exceptions=True)
        registry._conns.pop(me.id, None)
    frames = [json.loads(f) for f in sock.sent]
    assert [f["type"] for f in frames] == ["run_start", "run_cancel"]
    assert {f["run_id"] for f in frames} == {runs[0]["id"]}
    # the runner is alive: the run stays running until its run_finished arrives
    row = (await db.execute(select(AgentRun).execution_options(populate_existing=True))).scalar_one()
    assert row.status == "running"
