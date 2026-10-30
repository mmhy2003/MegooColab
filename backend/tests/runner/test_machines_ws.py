"""One runner per machine: a runner works only for the agents linked to its token (plan 17)."""

from fastapi.testclient import TestClient

from tests.agent_runs.test_dispatch import _run_status, _start, _task
from tests.agent_runs.test_run_guards import _next_of
from tests.runner.test_runner_ws import (
    URL,
    _agent,
    _expect_close,
    _hello,
    _manager_with_project,
    _mint,
    _next_welcome,
    _wait_status,
)


async def _two_machines(db, tc: TestClient):
    """A manager with tokens Yoga and Legion, and agents A (Yoga), B (Legion) and C (unlinked), all bound to PAY."""
    me, _ = await _manager_with_project(db, tc)
    yoga, legion = _mint(tc, name="Yoga"), _mint(tc, name="Legion")
    a = _agent(tc, name="A", runner_token_id=yoga["id"])
    b = _agent(tc, name="B", program="codex", runner_token_id=legion["id"])
    c = _agent(tc, name="C", runner_token_id=None)
    for agent in (a, b, c):
        r = tc.put(f"/api/agents/{agent['id']}/bindings",
                   json={"bindings": [{"project_ref": "PAY", "local_path": "/repo/pay"}]})
        assert r.status_code == 200, r.text
    return me, yoga, legion, a, b, c


def _all_available(*agents) -> dict:
    return _hello([{"agent_id": x["id"], "available": True, "problems": []} for x in agents])


async def test_runner_is_sent_only_its_tokens_agents(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, _, legion, _, b, _ = await _two_machines(db, tc)
    with tc.websocket_connect(URL, headers=legion["headers"]) as ws:
        assert [x["agent_id"] for x in ws.receive_json()["agents"]] == [b["id"]]


async def test_two_machines_online_at_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, yoga, legion, a, b, c = await _two_machines(db, tc)
    with tc.websocket_connect(URL, headers=yoga["headers"]) as ws_yoga:
        ws_yoga.receive_json()
        ws_yoga.send_json(_all_available(a, b, c))
        with tc.websocket_connect(URL, headers=legion["headers"]) as ws_legion:
            ws_legion.receive_json()
            ws_legion.send_json(_all_available(a, b, c))
            _wait_status(tc, a["id"], "online")
            _wait_status(tc, b["id"], "online")
            assert next(x for x in tc.get("/api/agents/mine").json() if x["id"] == c["id"])["status"] == "offline"
            # both sockets are still served
            ws_yoga.send_json({"type": "agent_status", "agent_id": a["id"], "available": False, "problems": []})
            _wait_status(tc, a["id"], "offline")
            _wait_status(tc, b["id"], "online")


async def test_same_token_twice_still_replaces(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, yoga, _, a, _, _ = await _two_machines(db, tc)
    with tc.websocket_connect(URL, headers=yoga["headers"]) as first:
        first.receive_json()
        with tc.websocket_connect(URL, headers=yoga["headers"]) as second:
            second.receive_json()
            _expect_close(first, 4409)


async def test_unlinked_agent_stays_offline(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, yoga, _, a, _, c = await _two_machines(db, tc)
    with tc.websocket_connect(URL, headers=yoga["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_all_available(c, a))
        _wait_status(tc, a["id"], "online")  # the whole hello has been processed
        _wait_status(tc, c["id"], "offline")


async def test_relinking_moves_agent_between_runners(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, yoga, legion, a, b, _ = await _two_machines(db, tc)
    with tc.websocket_connect(URL, headers=yoga["headers"]) as ws_yoga:
        ws_yoga.receive_json()
        with tc.websocket_connect(URL, headers=legion["headers"]) as ws_legion:
            ws_legion.receive_json()
            r = tc.patch(f"/api/agents/{a['id']}", json={"runner_token_id": legion["id"]})
            assert r.status_code == 200, r.text
            assert ws_yoga.receive_json()["type"] == "config_changed"
            assert [x["agent_id"] for x in _next_welcome(ws_yoga)["agents"]] == []
            assert ws_legion.receive_json()["type"] == "config_changed"
            assert {x["agent_id"] for x in _next_welcome(ws_legion)["agents"]} == {a["id"], b["id"]}


async def test_queued_run_dispatches_to_linked_machine(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, yoga, legion, a, _, _ = await _two_machines(db, tc)
    task = _task(tc, a)
    with tc.websocket_connect(URL, headers=legion["headers"]) as ws_legion:
        ws_legion.receive_json()
        ws_legion.send_json(_all_available(a))
        ws_legion.send_json({"type": "heartbeat"})
        run = _start(tc, task)
        assert _run_status(tc, task, run["id"]) == "queued"
        with tc.websocket_connect(URL, headers=yoga["headers"]) as ws_yoga:
            ws_yoga.receive_json()
            ws_yoga.send_json(_all_available(a))
            assert _next_of(ws_yoga, "run_start")["run_id"] == run["id"]


async def test_runner_info_is_the_agents_own_machine(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, yoga, legion, a, b, c = await _two_machines(db, tc)
    old, new = _all_available(a), _all_available(b)
    old["runner_version"], new["runner_version"] = "0.1.0", "0.2.0"
    with tc.websocket_connect(URL, headers=yoga["headers"]) as ws_yoga:
        ws_yoga.receive_json()
        ws_yoga.send_json(old)
        with tc.websocket_connect(URL, headers=legion["headers"]) as ws_legion:
            ws_legion.receive_json()
            ws_legion.send_json(new)
            _wait_status(tc, a["id"], "online")
            _wait_status(tc, b["id"], "online")
            runner = {x["id"]: x["runner"] for x in tc.get("/api/agents/mine").json()}
            assert runner[a["id"]]["version"] == "0.1.0"
            assert runner[b["id"]]["version"] == "0.2.0"
            assert runner[c["id"]] is None
