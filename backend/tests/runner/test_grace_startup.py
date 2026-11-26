"""After a restart (MC-214): a running run waits for its runner and fails if it never comes back."""

import time
import uuid

from sqlalchemy import update

from app.agent_runs.models import AgentRun
from app.core.config import get_settings
from app.runner import grace
from tests.agent_runs.test_dispatch import _setup, queue_run
from tests.runner.test_grace import _resume_hello, _status, _wait_run_id
from tests.runner.test_runner_ws import URL, _manager_with_project


async def _running_run_before_startup(db, tc_factory, monkeypatch, grace_seconds: float):
    """A run left running by the previous process, then the app starts."""
    tc = tc_factory()
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = await queue_run(task["key"])
    await db.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(run["id"])).values(status="running"))
    await db.commit()
    monkeypatch.setattr(get_settings(), "runner_grace_seconds", grace_seconds)
    monkeypatch.setattr(grace, "MARGIN_SECONDS", 0)
    return tc_factory(lifespan=True), token, agent, run


async def test_a_running_run_fails_at_the_deadline_after_a_restart(db, tc_factory, monkeypatch):
    tc, _, _, run = await _running_run_before_startup(db, tc_factory, monkeypatch, 0.3)
    _wait_run_id(tc, run["id"], "failed", within=5)
    assert tc.portal.call(_status, run["id"]) == ("failed", "runner_disconnected")


async def test_a_runner_that_returns_after_a_restart_keeps_its_run(db, tc_factory, monkeypatch):
    tc, token, agent, run = await _running_run_before_startup(db, tc_factory, monkeypatch, 2)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_resume_hello(agent))
        ws.send_json({"type": "runs_held", "runs": [run["id"]]})
        time.sleep(2.5)  # past the startup deadline
        assert tc.portal.call(_status, run["id"]) == ("running", None)
        ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "completed", "summary": "ok"})
        _wait_run_id(tc, run["id"], "completed")
