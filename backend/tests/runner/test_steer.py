"""A message for the agent reaches its running session: run_steer out, run_steer_result back."""

from tests.agent_runs.test_dispatch import _avail, _setup, _start, _wait_run
from tests.runner.test_runner_ws import URL, _hello, _manager_with_project

STEER = ("workflow/1", "branch/1", "model/1", "steer/1")


def _state(tc, task, comment_id):
    item = next(i for i in tc.get(f"/api/tasks/{task['key']}/activity").json() if i["id"] == comment_id)
    return item["to_agent"]


def _send(tc, task, body="Use RetryPolicy"):
    r = tc.post(f"/api/tasks/{task['key']}/comments", json={"body_md": body, "to_agent": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _running(tc, ws, agent, capabilities=STEER):
    ws.receive_json()  # welcome
    ws.send_json(_hello([_avail(agent)], capabilities=capabilities))
    start = ws.receive_json()
    assert start["type"] == "run_start"
    return start


def _result(ws, steer, outcome, error=None):
    msg = {"type": "run_steer_result", "run_id": steer["run_id"], "message_id": steer["message_id"], "outcome": outcome}
    if error:
        msg["error"] = error
    ws.send_json(msg)
    ws.send_json({"type": "heartbeat"})


def _until(check):
    import time

    deadline = time.monotonic() + 3
    while not check():
        assert time.monotonic() < deadline, "condition never met"
        time.sleep(0.02)


async def test_message_while_running_is_steered_and_injected(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _running(tc, ws, agent)
        cid = _send(tc, task)
        steer = ws.receive_json()
        assert steer["type"] == "run_steer" and steer["run_id"] == run["id"] and steer["message_id"] == cid
        assert steer["text"].startswith("MegooColab: a person who directs") and "> Use RetryPolicy" in steer["text"]
        assert _state(tc, task, cid)["state"] == "sending"
        _result(ws, steer, "injected")
        _until(lambda: _state(tc, task, cid)["state"] == "read_while_working")
        assert _state(tc, task, cid)["delivered_at"] is not None


async def test_not_running_result_puts_it_back_to_waiting(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _running(tc, ws, agent)
        cid = _send(tc, task)
        _result(ws, ws.receive_json(), "not_running")
        _until(lambda: _state(tc, task, cid)["state"] == "waiting")
        assert _state(tc, task, cid)["error"] is None


async def test_failed_result_keeps_the_error(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _running(tc, ws, agent)
        cid = _send(tc, task)
        _result(ws, ws.receive_json(), "failed", "boom")
        _until(lambda: _state(tc, task, cid)["state"] == "waiting")
        assert _state(tc, task, cid)["error"] == "boom"


async def test_runner_without_steer_capability_gets_no_frame(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _running(tc, ws, agent, capabilities=("workflow/1", "branch/1", "model/1"))
        cid = _send(tc, task)
        assert _state(tc, task, cid)["state"] == "waiting"
        ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "completed", "summary": "ok"})
        _wait_run(tc, task, run["id"], "completed")  # the next frame would have been a run_steer otherwise


async def test_run_finishing_releases_a_sending_message(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _running(tc, ws, agent)
        cid = _send(tc, task)
        ws.receive_json()  # the steer, never answered
        ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "completed", "summary": "ok"})
        _wait_run(tc, task, run["id"], "completed")
        assert _state(tc, task, cid)["state"] == "waiting"


async def test_result_from_another_run_is_ignored(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _running(tc, ws, agent)
        cid = _send(tc, task)
        steer = ws.receive_json()
        _result(ws, {**steer, "run_id": "00000000-0000-0000-0000-000000000001"}, "injected")
        assert _state(tc, task, cid)["state"] == "sending"


async def test_queued_run_is_not_steered(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    _, _, task = _setup(tc)
    _start(tc, task)  # no runner connected: the run stays queued
    cid = _send(tc, task)
    assert _state(tc, task, cid)["state"] == "waiting"
