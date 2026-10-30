"""Final review guards: deleting mid-run (I3), lost project access (I4), one active run per task (I5)."""

import asyncio
import json
import uuid

from sqlalchemy import delete, func, select, update

from app.agent_runs.models import AgentRun
from app.agent_runs.service import cancel_user_runs, fail_disconnected_runs
from app.auth.models import Role
from app.core.db import SessionLocal
from app.runner.registry import registry
from app.tasks.models import TaskEvent
from app.teams.models import TeamMember
from app.workflow import methodology
from tests.agent_runs.test_dispatch import (
    _avail,
    _dispatch_in_own_session,
    _event_kinds,
    _fake_conn,
    _FakeSocket,
    _offline_runs,
    _setup,
    _start,
    _task,
    _wait_run,
)
from tests.factories import login, make_project, make_user
from tests.mcp.test_mcp import _mint as _mint_mcp
from tests.mcp.test_mcp import call, mcp_session
from tests.runner.test_runner_ws import (
    URL,
    _hello,
    _login,
    _manager_with_project,
)


def _next_of(ws, type_: str) -> dict:
    """The next frame of this type; welcome / config_changed frames in between are skipped."""
    while True:
        msg = ws.receive_json()
        if msg["type"] == type_:
            return msg
        assert msg["type"] in {"welcome", "config_changed"}, msg


def _finish(ws, run_id: str, outcome: str = "cancelled") -> None:
    ws.send_json({"type": "run_finished", "run_id": run_id, "outcome": outcome, "summary": "stopped"})


# ---- I3: deleting a task or project mid-run ---------------------------------


async def test_deleting_a_task_cancels_its_running_run(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    other = _task(tc, agent, title="Other")
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert _next_of(ws, "run_start")["run_id"] == run["id"]
        _wait_run(tc, task, run["id"], "running")
        assert tc.delete(f"/api/tasks/{task['key']}").status_code == 204
        second = _start(tc, other)  # the slot is free again: this one is dispatched at once
        assert ws.receive_json() == {"type": "run_cancel", "run_id": run["id"]}
        assert ws.receive_json()["run_id"] == second["id"]
        # the runner's late run_finished for the deleted run is ignored and the socket stays usable
        _finish(ws, run["id"])
        assert tc.post(f"/api/agent-runs/{second['id']}/cancel").status_code == 204
        assert ws.receive_json() == {"type": "run_cancel", "run_id": second["id"]}
    assert (await db.execute(select(AgentRun.id).where(AgentRun.id == run["id"]))).first() is None


async def test_deleting_a_task_drops_its_queued_run_without_a_cancel(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    other = _task(tc, agent, title="Other")
    first = _start(tc, other)
    queued = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert _next_of(ws, "run_start")["run_id"] == first["id"]  # max 1: the second waits
        assert tc.delete(f"/api/tasks/{task['key']}").status_code == 204
        _finish(ws, first["id"], "completed")
        ws.send_json({"type": "agent_status", "agent_id": agent["id"], "available": True, "problems": []})
        _wait_run(tc, other, first["id"], "completed")
        ws.send_json({"type": "heartbeat"})
    rows = (await db.execute(select(AgentRun.id))).scalars().all()
    assert [str(r) for r in rows] == [first["id"]]  # the queued run went with its task, never started
    assert queued["id"] not in [str(r) for r in rows]


async def test_deleting_a_project_cancels_its_running_runs(db, tc_factory):
    tc, ac = tc_factory(lifespan=True), tc_factory()
    admin = await make_user(db, role=Role.admin)
    _login(ac, admin)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    team_id = tc.get("/api/projects/PAY").json()["team_ids"][0]
    r = tc.post("/api/projects", json={"key": "QA", "name": "QA", "description": "", "team_ids": [team_id]})
    assert r.status_code == 201, r.text
    bindings = [{"project_ref": k, "local_path": f"/repo/{k}"} for k in ("PAY", "QA")]
    assert tc.put(f"/api/agents/{agent['id']}/bindings", json={"bindings": bindings}).status_code == 200
    kept = _task(tc, agent, ref="QA", title="Kept")
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert _next_of(ws, "run_start")["run_id"] == run["id"]
        _wait_run(tc, task, run["id"], "running")
        assert ac.delete("/api/projects/PAY").status_code == 204
        second = _start(tc, kept)  # the slot is free again: this one is dispatched at once
        frames = [ws.receive_json()]
        while frames[-1]["type"] != "run_start":
            frames.append(ws.receive_json())
        assert frames[-1]["run_id"] == second["id"]
        assert {"type": "run_cancel", "run_id": run["id"]} in frames
        _finish(ws, run["id"])
        assert tc.post(f"/api/agent-runs/{second['id']}/cancel").status_code == 204
        assert _next_of(ws, "run_cancel") == {"type": "run_cancel", "run_id": second["id"]}
    assert [str(r) for r in (await db.execute(select(AgentRun.id))).scalars()] == [second["id"]]


async def test_deleting_a_story_cancels_its_subtasks_running_run(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, other = _setup(tc)
    story = tc.post("/api/projects/PAY/tasks", json={"title": "Story", "type": "story"}).json()
    sub = _task(tc, agent, title="Sub", type="subtask", parent_id=story["id"])
    run = _start(tc, sub)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert _next_of(ws, "run_start")["run_id"] == run["id"]
        _wait_run(tc, sub, run["id"], "running")
        assert tc.delete(f"/api/tasks/{story['key']}").status_code == 204
        assert tc.get(f"/api/tasks/{sub['key']}").status_code == 404  # the cascade took the subtask
        second = _start(tc, other)
        assert ws.receive_json() == {"type": "run_cancel", "run_id": run["id"]}
        assert ws.receive_json()["run_id"] == second["id"]
        _finish(ws, run["id"])


# ---- I4: an agent whose owner lost access to the project --------------------


async def _drop_from_teams(db, user) -> None:
    await db.execute(delete(TeamMember).where(TeamMember.user_id == user.id))
    await db.commit()


async def _ex_member_agent(client, client_factory, db):
    """A member binds an agent to PAY, gets a task assigned to it, then leaves the project's team.
    Returns (manager_client, agent, assigned_task, unassigned_task)."""
    me = await make_user(db)
    _, manager, _ = await make_project(client, db, "PAY", me)
    await login(client, me)
    agent = (await client.post("/api/agents", json={"program": "claude_code"})).json()
    r = await client.put(
        f"/api/agents/{agent['id']}/bindings", json={"bindings": [{"project_ref": "PAY", "local_path": "/repo"}]}
    )
    assert r.status_code == 200
    assigned = (await client.post("/api/projects/PAY/tasks", json={"title": "A", "assignee_agent_id": agent["id"]})).json()
    plain = (await client.post("/api/projects/PAY/tasks", json={"title": "B"})).json()
    mc = client_factory()
    await login(mc, manager)
    assert len((await mc.get("/api/projects/PAY/agents")).json()) == 1
    await _drop_from_teams(db, me)
    return mc, agent, assigned, plain


async def test_ex_member_agent_is_not_assignable_runnable_or_listed(client, client_factory, db):
    mc, agent, assigned, plain = await _ex_member_agent(client, client_factory, db)
    r = await mc.patch(f"/api/tasks/{plain['key']}", json={"assignee_agent_id": agent["id"]})
    assert r.status_code == 422 and r.json()["detail"] == "agent_not_bound"
    r = await mc.post("/api/projects/PAY/tasks", json={"title": "C", "assignee_agent_id": agent["id"]})
    assert r.status_code == 422 and r.json()["detail"] == "agent_not_bound"
    r = await mc.post(f"/api/tasks/{assigned['key']}/workflow/start")
    assert r.status_code == 422 and r.json()["detail"] == "agent_not_bound"
    assert (await mc.get("/api/projects/PAY/agents")).json() == []
    assert (await db.execute(select(AgentRun))).first() is None


async def test_ex_member_agent_not_assignable_over_mcp(app, client, client_factory, db, mcp_running):
    mc, agent, _assigned, _plain = await _ex_member_agent(client, client_factory, db)
    async with mcp_session(app, await _mint_mcp(mc)) as s:
        is_error, payload = await call(s, "create_task", project_key="PAY", title="X", assignee_agent_id=agent["id"])
    assert is_error and "agent_not_bound" in payload


async def test_queued_run_of_an_ex_member_fails_instead_of_being_sent(client, db):
    me, agent, runs = await _offline_runs(client, db)
    await _drop_from_teams(db, me)
    sock = _FakeSocket()
    await _fake_conn(me, agent, sock)
    try:
        await _dispatch_in_own_session(me.id)
    finally:
        registry._conns.pop(me.id, None)
    assert [json.loads(f)["type"] for f in sock.sent] == []
    row = (await db.execute(select(AgentRun).where(AgentRun.id == uuid.UUID(runs[0]["id"])))).scalar_one()
    assert row.status == "failed" and row.reason == "owner_lost_access"
    assert "agent_run_failed" in await _event_kinds(db)


# ---- I5: one active run per task ---------------------------------------------


async def test_second_run_of_a_task_is_409_while_one_is_active(client, db):
    _me, _agent, runs = await _offline_runs(client, db)
    key = runs[0]["task_key"]
    await methodology.seed_defaults(db)
    await db.commit()
    r = await client.post(f"/api/tasks/{key}/workflow/start")
    assert r.status_code == 409 and r.json()["detail"] == "task_has_active_run"
    await db.execute(update(AgentRun).values(status="running"))
    await db.commit()
    r = await client.post(f"/api/tasks/{key}/workflow/start")
    assert r.status_code == 409 and r.json()["detail"] == "task_has_active_run"
    await db.execute(update(AgentRun).values(status="completed"))
    await db.commit()
    assert (await client.post(f"/api/tasks/{key}/workflow/start")).status_code == 200
    assert len((await db.execute(select(AgentRun))).all()) == 2


async def test_concurrent_starts_of_one_task_make_one_run(client, db):
    _me, _agent, runs = await _offline_runs(client, db)
    key = runs[0]["task_key"]
    await methodology.seed_defaults(db)
    await db.execute(update(AgentRun).values(status="completed"))
    await db.commit()
    results = await asyncio.gather(*[client.post(f"/api/tasks/{key}/workflow/start") for _ in range(4)])
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409]
    assert (await db.execute(select(func.count()).select_from(AgentRun).where(AgentRun.status == "queued"))).scalar() == 1


async def test_dispatch_skips_a_queued_run_whose_task_is_already_running(client, db):
    me, agent, runs = await _offline_runs(client, db, n=2, max_runs=3)
    first, second = (uuid.UUID(r["id"]) for r in runs)
    # forced past the API's 409: the first task now has a running run and a second queued one
    await db.execute(update(AgentRun).where(AgentRun.id == first).values(status="running"))
    row = await db.get(AgentRun, second)
    db.add(AgentRun(task_id=(await db.get(AgentRun, first)).task_id, agent_id=row.agent_id,
                    requested_by=row.requested_by, policy="read_only", prompt="again"))
    await db.commit()
    sock = _FakeSocket()
    await _fake_conn(me, agent, sock)
    try:
        await _dispatch_in_own_session(me.id)
    finally:
        registry._conns.pop(me.id, None)
    started = [f["run_id"] for f in map(json.loads, sock.sent) if f["type"] == "run_start"]
    assert started == [str(second)]  # the duplicate for the running task stays queued
    statuses = sorted((await db.execute(select(AgentRun.status))).scalars())
    assert statuses == ["queued", "running", "running"]


# ---- M10: every agent_run_* event names its agent -----------------------------


async def test_every_agent_run_event_carries_the_agent_id(client, db):
    me, agent, runs = await _offline_runs(client, db, n=3, max_runs=3)
    conn = await _fake_conn(me, agent, _FakeSocket())
    try:
        await _dispatch_in_own_session(me.id)  # started x3
        registry._conns.pop(me.id, None)
        # user cancel with the runner gone; runner disconnect; owner deactivation
        assert (await client.post(f"/api/agent-runs/{runs[0]['id']}/cancel")).status_code == 204
        async with SessionLocal() as s:
            await s.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(runs[1]["id"])).values(status="running"))
            conn.run_ids.discard(uuid.UUID(runs[2]["id"]))
            await s.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(runs[2]["id"])).values(status="queued"))
            await fail_disconnected_runs(s, conn)
            await cancel_user_runs(s, me.id)
            await s.commit()
    finally:
        registry._conns.pop(me.id, None)
    rows = (await db.execute(select(TaskEvent).where(TaskEvent.kind.like("agent_run_%")))).scalars().all()
    kinds = {e.kind for e in rows}
    assert kinds == {"agent_run_queued", "agent_run_started", "agent_run_cancelled", "agent_run_failed"}
    assert [e.kind for e in rows if e.data.get("agent_id") != agent["id"]] == []
