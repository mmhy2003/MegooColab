"""Final review guards: deleting mid-run (I3), lost project access (I4), one active run per task (I5)."""

from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.auth.models import Role
from tests.agent_runs.test_dispatch import _avail, _setup, _start, _task, _wait_run
from tests.factories import make_user
from tests.runner.test_runner_ws import (  # noqa: F401  (tc_factory is a fixture)
    URL,
    _hello,
    _login,
    _manager_with_project,
    tc_factory,
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
    me, _ = await _manager_with_project(db, tc)
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
