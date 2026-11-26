"""The grace period (MC-214): a dropped resume/1 runner's running runs wait for it, and its runs_held settles them."""

import time
import uuid

import pytest
from sqlalchemy import func, select, update

from app.agent_runs.models import AgentRun
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.notifications.models import Notification
from app.runner import grace
from app.runner.registry import registry
from app.tasks.models import TaskEvent
from tests.agent_runs.test_dispatch import _avail, _setup, _start, _task, _wait_run
from tests.agent_runs.test_run_guards import _next_of
from tests.runner.test_runner_ws import (
    CURRENT_CAPABILITIES,
    URL,
    _expect_close,
    _hello,
    _manager_with_project,
)
from tests.workflow.test_engine import _runs, _started, _until, _wf

RESUME = CURRENT_CAPABILITIES + ("resume/1",)


@pytest.fixture(autouse=True)
def _grace(monkeypatch):
    """Grace 60 and the usual margin unless a test sets them (the app's shutdown cancels the deadlines)."""
    monkeypatch.setattr(get_settings(), "runner_grace_seconds", 60)


def _set_grace(monkeypatch, seconds: float, margin: float = 30) -> None:
    monkeypatch.setattr(get_settings(), "runner_grace_seconds", seconds)
    monkeypatch.setattr(grace, "MARGIN_SECONDS", margin)


def _resume_hello(agent) -> dict:
    return _hello([_avail(agent)], capabilities=RESUME)


def _connect_and_run(tc, token, agent, run_id: str, capabilities=RESUME) -> None:
    """A runner connects, says hello and is given the queued run, which then runs."""
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)], capabilities=capabilities))
        assert _next_of(ws, "run_start")["run_id"] == run_id
        _wait_run_id(tc, run_id, "running")


async def _status(run_id) -> tuple[str, str | None]:
    async with SessionLocal() as s:
        run = await s.get(AgentRun, uuid.UUID(str(run_id)))
        return run.status, run.reason


def _wait_run_id(tc, run_id, expected, within: float = 3) -> None:
    deadline = time.monotonic() + within
    while (got := tc.portal.call(_status, run_id))[0] != expected:
        assert time.monotonic() < deadline, f"run stayed {got}, wanted {expected}"
        time.sleep(0.02)


async def _count(model, *where) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(model).where(*where))


async def test_a_drop_inside_the_grace_period_fails_nothing(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    _connect_and_run(tc, b.token, b.agent, str(run.id))
    time.sleep(0.5)
    assert tc.portal.call(_status, run.id) == ("running", None)
    assert await _count(TaskEvent, TaskEvent.task_id == b.task_id, TaskEvent.kind == "agent_run_failed") == 0
    assert await _count(Notification, Notification.kind == "agent_offline") == 0
    assert (await _wf(b.task_id)).failures == 0
    # the agent is no longer available (its status stays busy: it has a running run)
    assert not registry.is_available(uuid.UUID(b.agent["id"]))

    with tc.websocket_connect(URL, headers=b.token["headers"]) as ws:
        assert ws.receive_json()["grace_seconds"] == 60
        ws.send_json(_resume_hello(b.agent))
        ws.send_json({"type": "runs_held", "runs": [str(run.id)]})
        ws.send_json({"type": "run_update", "run_id": str(run.id), "seq": 1, "kind": "message",
                      "data": {"text": "still here"}})
        ws.send_json({"type": "run_finished", "run_id": str(run.id), "outcome": "completed", "summary": "done"})
        _wait_run_id(tc, run.id, "completed")
    assert await _count(TaskEvent, TaskEvent.task_id == b.task_id, TaskEvent.kind == "agent_message") == 1
    assert (await _wf(b.task_id)).failures == 0


async def test_a_runner_that_does_not_return_fails_at_the_deadline(db, tc_factory, monkeypatch):
    _set_grace(monkeypatch, 1, margin=0)
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    _connect_and_run(tc, b.token, b.agent, str(run.id))
    assert tc.portal.call(_status, run.id) == ("running", None)

    async def failed():
        return (await _runs(b.task_id))[0].status == "failed"

    await _until(failed, "the run to fail at the deadline")
    assert (await _runs(b.task_id))[0].reason == "runner_disconnected"
    assert (await _wf(b.task_id)).failures == 1
    assert await _count(Notification, Notification.kind == "agent_offline") >= 1


async def test_runs_held_cancels_a_run_no_longer_running_and_fails_unlisted_ones(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    a = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_resume_hello(agent))
        assert _next_of(ws, "run_start")["run_id"] == a["id"]
        _wait_run(tc, task, a["id"], "running")
        b = _start(tc, _task(tc, agent, title="Other"))  # queued behind A (one run at once) and never sent
        await db.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(b["id"])).values(status="running"))
        await db.commit()
    assert tc.post(f"/api/agent-runs/{a['id']}/cancel").status_code == 204
    assert tc.portal.call(_status, a["id"])[0] == "cancelled"
    assert tc.portal.call(_status, b["id"]) == ("running", None)

    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_resume_hello(agent))
        ws.send_json({"type": "runs_held", "runs": [a["id"]]})
        assert _next_of(ws, "run_cancel") == {"type": "run_cancel", "run_id": a["id"]}
        _wait_run_id(tc, b["id"], "failed")
    assert tc.portal.call(_status, b["id"]) == ("failed", "runner_disconnected")


async def test_a_runner_without_resume_fails_at_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    _connect_and_run(tc, token, agent, run["id"], capabilities=CURRENT_CAPABILITIES)
    _wait_run_id(tc, run["id"], "failed")
    assert tc.portal.call(_status, run["id"]) == ("failed", "runner_disconnected")


async def test_unauthorized_close_cancels_at_once_even_with_resume(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_resume_hello(agent))
        assert _next_of(ws, "run_start")["run_id"] == run["id"]
        _wait_run(tc, task, run["id"], "running")
        assert tc.delete(f"/api/tokens/{token['id']}").status_code == 204
        _expect_close(ws, 4401)
    _wait_run_id(tc, run["id"], "cancelled")
    assert tc.portal.call(_status, run["id"]) == ("cancelled", "runner_unauthorized")


async def test_hello_from_a_resume_runner_leaves_running_runs_for_runs_held(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    orphan = _start(tc, task)
    await db.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(orphan["id"])).values(status="running"))
    await db.commit()
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_resume_hello(agent))
        time.sleep(0.5)
        assert tc.portal.call(_status, orphan["id"]) == ("running", None)
        ws.send_json({"type": "runs_held", "runs": []})
        _wait_run_id(tc, orphan["id"], "failed")
    assert tc.portal.call(_status, orphan["id"]) == ("failed", "runner_disconnected")


async def test_a_replaced_connection_keeps_its_runs(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as first:
        first.receive_json()
        first.send_json(_resume_hello(agent))
        assert _next_of(first, "run_start")["run_id"] == run["id"]
        _wait_run(tc, task, run["id"], "running")
        with tc.websocket_connect(URL, headers=token["headers"]) as second:
            second.receive_json()
            _expect_close(first, 4409)
            second.send_json(_resume_hello(agent))
            second.send_json({"type": "runs_held", "runs": [run["id"]]})
            time.sleep(0.5)
            assert tc.portal.call(_status, run["id"]) == ("running", None)
            second.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "completed", "summary": "ok"})
            _wait_run_id(tc, run["id"], "completed")


async def test_the_deadline_waits_for_runs_held_from_a_live_runner(db, tc_factory, monkeypatch):
    _set_grace(monkeypatch, 1, margin=0)  # the setting is whole seconds
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    _connect_and_run(tc, token, agent, run["id"])
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_resume_hello(agent))
        time.sleep(1.5)  # past the deadline
        assert tc.portal.call(_status, run["id"]) == ("running", None)
        ws.send_json({"type": "runs_held", "runs": [run["id"]]})
        time.sleep(0.5)
        assert tc.portal.call(_status, run["id"]) == ("running", None)


async def test_grace_zero_fails_at_once(db, tc_factory, monkeypatch):
    _set_grace(monkeypatch, 0)
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        assert ws.receive_json()["grace_seconds"] == 0
        ws.send_json(_resume_hello(agent))
        assert _next_of(ws, "run_start")["run_id"] == run["id"]
        _wait_run(tc, task, run["id"], "running")
    _wait_run_id(tc, run["id"], "failed")
    assert tc.portal.call(_status, run["id"]) == ("failed", "runner_disconnected")
