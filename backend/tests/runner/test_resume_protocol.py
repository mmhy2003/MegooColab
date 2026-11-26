"""The resume protocol (MC-214): the welcome's grace period and the runner's runs_held message."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.runner import protocol
from app.runner.protocol import runner_message
from tests.runner.test_runner_ws import URL, _agent, _hello, _owner, _wait_status


async def test_welcome_carries_the_grace_period(db, tc_factory, monkeypatch):
    tc = tc_factory(lifespan=True)
    _, token = await _owner(db, tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        assert ws.receive_json()["grace_seconds"] == 60
    monkeypatch.setattr(get_settings(), "runner_grace_seconds", 0)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        assert ws.receive_json()["grace_seconds"] == 0


def test_runs_held_validates():
    run_id = uuid4()
    msg = runner_message.validate_python({"type": "runs_held", "runs": [str(run_id)]})
    assert isinstance(msg, protocol.RunsHeld) and msg.runs == [run_id]
    assert runner_message.validate_python({"type": "runs_held"}).runs == []
    for bad in (
        {"type": "runs_held", "runs": [str(uuid4()) for _ in range(201)]},
        {"type": "runs_held", "runs": [], "extra": 1},
        {"type": "runs_held", "runs": ["not-a-uuid"]},
    ):
        with pytest.raises(ValidationError):
            runner_message.validate_python(bad)


async def test_runs_held_does_not_close_the_socket(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, token = await _owner(db, tc)
    a = _agent(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json({"type": "runs_held", "runs": []})
        ws.send_json(_hello([{"agent_id": a["id"], "available": True, "problems": []}]))
        _wait_status(tc, a["id"], "online")
