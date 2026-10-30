"""Runner WebSocket tests; same TestClient setup as tests/realtime/test_ws.py."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth.models import Role
from tests.factories import DEFAULT_PASSWORD, make_team, make_user

URL = "/api/runner/ws"


def _login(tc: TestClient, user) -> None:
    r = tc.post("/api/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD})
    assert r.status_code == 200, r.text


def _mint(tc: TestClient, scopes=("runner",), name: str = "laptop") -> dict:
    """A token; a runner one is also remembered on `tc`, and _agent links new agents to it."""
    r = tc.post("/api/tokens", json={"name": name, "scopes": list(scopes)})
    assert r.status_code == 201, r.text
    if "runner" in scopes:
        tc.runner_token_id = r.json()["token"]["id"]
    return {"id": r.json()["token"]["id"], "headers": {"Authorization": f"Bearer {r.json()['secret']}"}}


def _agent(tc: TestClient, **body) -> dict:
    """An agent, linked to the runner token last minted on `tc` unless runner_token_id is given."""
    body.setdefault("program", "claude_code")
    body.setdefault("runner_token_id", getattr(tc, "runner_token_id", None))
    r = tc.post("/api/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _status(tc: TestClient, agent_id: str) -> str:
    return next(a["status"] for a in tc.get("/api/agents/mine").json() if a["id"] == agent_id)


def _wait_status(tc: TestClient, agent_id: str, expected: str) -> None:
    """Runner messages are processed asynchronously: poll until the status settles."""
    deadline = time.monotonic() + 3
    while _status(tc, agent_id) != expected:
        assert time.monotonic() < deadline, f"status stayed {_status(tc, agent_id)}, wanted {expected}"
        time.sleep(0.02)


CURRENT_CAPABILITIES = ("workflow/1", "branch/1")


def _hello(agents: list[dict], capabilities=CURRENT_CAPABILITIES) -> dict:
    """A current runner's hello; capabilities=None is a v1 runner's (no capabilities field)."""
    hello = {"type": "hello", "runner_version": "0.1.0", "os": "linux", "arch": "amd64", "agents": agents}
    if capabilities is not None:
        hello["capabilities"] = list(capabilities)
    return hello


def _expect_close(ws, code: int) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        while True:
            ws.receive_json()
    assert exc.value.code == code


def _next_welcome(ws) -> dict:
    while True:
        msg = ws.receive_json()
        if msg["type"] == "welcome":
            return msg


async def _manager_with_project(db, tc: TestClient, key: str = "PAY"):
    """A manager logged in on `tc`, with a project they can bind agents to."""
    me = await make_user(db, role=Role.manager)
    team = await make_team(db, me)
    _login(tc, me)
    r = tc.post("/api/projects", json={"key": key, "name": key, "description": "", "team_ids": [str(team.id)]})
    assert r.status_code == 201, r.text
    return me, r.json()


async def _owner(db, tc: TestClient):
    user = await make_user(db)
    _login(tc, user)
    return user, _mint(tc)


async def test_runner_ws_rejects_missing_or_mcp_only_token(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, _ = await _owner(db, tc)
    mcp_only = _mint(tc, scopes=("mcp",))
    for headers in ({}, {"Authorization": "Bearer mgc_bogus"}, mcp_only["headers"]):
        with pytest.raises(WebSocketDisconnect) as exc:
            with tc.websocket_connect(URL, headers=headers) as ws:
                ws.receive_json()
        assert exc.value.code == 4401


async def test_welcome_lists_agents_and_bindings(db, tc_factory):
    tc = tc_factory(lifespan=True)
    me, _ = await _manager_with_project(db, tc)
    token = _mint(tc)
    a = _agent(tc, max_concurrent_runs=2)
    r = tc.put(
        f"/api/agents/{a['id']}/bindings",
        json={"bindings": [{"project_ref": "PAY", "local_path": "/home/me/pay"}]},
    )
    assert r.status_code == 200, r.text
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        msg = ws.receive_json()
        assert msg == {
            "type": "welcome",
            "user_id": str(me.id),
            "agents": [
                {
                    "agent_id": a["id"],
                    "name": a["name"],
                    "program": "claude_code",
                    "max_concurrent_runs": 2,
                    "bindings": [{"project_key": "PAY", "local_path": "/home/me/pay"}],
                }
            ],
        }


async def test_hello_marks_agent_online_and_disconnect_offline(db, tc_factory):
    tc = tc_factory(lifespan=True)
    me, token = await _owner(db, tc)
    a, b = _agent(tc), _agent(tc, program="codex")
    _wait_status(tc, a["id"], "offline")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(
            _hello(
                [
                    {"agent_id": a["id"], "available": True, "problems": []},
                    {"agent_id": b["id"], "available": False, "problems": ["codex not installed"]},
                ]
            )
        )
        ws.send_json({"type": "heartbeat"})  # processed after the hello
        _wait_status(tc, a["id"], "online")
        _wait_status(tc, b["id"], "offline")
        ws.send_json({"type": "agent_status", "agent_id": b["id"], "available": True, "problems": []})
        ws.send_json({"type": "agent_status", "agent_id": a["id"], "available": False, "problems": ["x"]})
        ws.send_json({"type": "heartbeat"})
        _wait_status(tc, a["id"], "offline")
        _wait_status(tc, b["id"], "online")
    _wait_status(tc, b["id"], "offline")


async def test_hello_ignores_agents_the_user_does_not_own(db, tc_factory):
    tc, other = tc_factory(lifespan=True), tc_factory()
    me, token = await _owner(db, tc)
    stranger = await make_user(db)
    _login(other, stranger)
    theirs = _agent(other)
    mine = _agent(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(
            _hello(
                [
                    {"agent_id": theirs["id"], "available": True, "problems": []},
                    {"agent_id": mine["id"], "available": True, "problems": []},
                ]
            )
        )
        _wait_status(tc, mine["id"], "online")  # the whole hello has been processed
        _wait_status(other, theirs["id"], "offline")


async def test_availability_change_publishes_agents_updated(db, tc_factory):
    tc = tc_factory(lifespan=True)
    me, project = await _manager_with_project(db, tc)
    token = _mint(tc)
    a = _agent(tc)
    tc.put(
        f"/api/agents/{a['id']}/bindings",
        json={"bindings": [{"project_ref": "PAY", "local_path": "/r"}]},
    )
    with tc.websocket_connect("/api/ws") as browser:
        with tc.websocket_connect(URL, headers=token["headers"]) as ws:
            ws.receive_json()
            ws.send_json(_hello([{"agent_id": a["id"], "available": True, "problems": []}]))
            seen = set()
            while "project" not in seen:
                m = browser.receive_json()
                if m["type"] == "agents.updated" and m["project_id"] == project["id"]:
                    seen.add("project")


async def test_second_runner_replaces_first_4409(db, tc_factory):
    tc = tc_factory(lifespan=True)
    me, token = await _owner(db, tc)
    a = _agent(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as first:
        first.receive_json()
        first.send_json(_hello([{"agent_id": a["id"], "available": True, "problems": []}]))
        with tc.websocket_connect(URL, headers=token["headers"]) as second:
            second.receive_json()
            _expect_close(first, 4409)
            # the replaced connection's cleanup must not unregister the new one
            second.send_json({"type": "heartbeat"})
            second.send_json(_hello([{"agent_id": a["id"], "available": True, "problems": []}]))
            second.send_json({"type": "heartbeat"})
            _wait_status(tc, a["id"], "online")


async def test_unknown_message_type_closes_4400(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, token = await _owner(db, tc)
    bad_messages = [
        {"type": "nope"},
        {"type": "heartbeat", "extra": 1},
        {"type": "run_finished", "run_id": "1", "outcome": "weird", "summary": "", "error": None},
    ]
    for bad in bad_messages:
        with tc.websocket_connect(URL, headers=token["headers"]) as ws:
            ws.receive_json()
            ws.send_json(bad)
            _expect_close(ws, 4400)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_text("not json")
        _expect_close(ws, 4400)


async def test_revoking_token_closes_runner(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, token = await _owner(db, tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        assert tc.delete(f"/api/tokens/{token['id']}").status_code == 204
        _expect_close(ws, 4401)


async def test_deactivation_closes_runner(db, tc_factory):
    tc, ac = tc_factory(lifespan=True), tc_factory()
    admin = await make_user(db, role=Role.admin)
    _login(ac, admin)
    member, token = await _owner(db, tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        assert ac.post(f"/api/admin/users/{member.id}/deactivate").status_code == 204
        _expect_close(ws, 4401)


async def test_binding_change_sends_new_welcome(db, tc_factory):
    tc = tc_factory(lifespan=True)
    me, _ = await _manager_with_project(db, tc)
    token = _mint(tc)
    a = _agent(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        assert ws.receive_json()["agents"][0]["bindings"] == []
        r = tc.put(
            f"/api/agents/{a['id']}/bindings",
            json={"bindings": [{"project_ref": "PAY", "local_path": "/r"}]},
        )
        assert r.status_code == 200
        assert ws.receive_json() == {"type": "config_changed"}
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome"
        assert welcome["agents"][0]["bindings"] == [{"project_key": "PAY", "local_path": "/r"}]


async def test_idle_runner_is_closed(db, tc_factory, monkeypatch):
    from app.runner import router as rr

    monkeypatch.setattr(rr, "IDLE_TIMEOUT_SECONDS", 0.3)
    tc = tc_factory(lifespan=True)
    _, token = await _owner(db, tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        with pytest.raises(WebSocketDisconnect):
            while True:
                ws.receive_json()


async def test_token_revalidated_periodically_without_events(db, tc_factory, monkeypatch):
    from sqlalchemy import update

    from app.auth.models import PersonalAccessToken
    from app.auth.service import now
    from app.runner import router as rr

    monkeypatch.setattr(rr, "REVALIDATE_EVERY_SECONDS", 0.2)
    tc = tc_factory(lifespan=True)
    _, token = await _owner(db, tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        # revoked straight in the database: no event is published
        await db.execute(update(PersonalAccessToken).values(revoked_at=now()))
        await db.commit()
        _expect_close(ws, 4401)


async def test_failed_publish_on_disconnect_is_logged(db, tc_factory, monkeypatch, caplog):
    from app.runner import router as rr

    async def boom(*_a, **_k):
        raise RuntimeError("publish down")

    tc = tc_factory(lifespan=True)
    _, token = await _owner(db, tc)
    a = _agent(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([{"agent_id": a["id"], "available": True, "problems": []}]))
        _wait_status(tc, a["id"], "online")
        monkeypatch.setattr(rr, "_publish_availability", boom)
    deadline = time.monotonic() + 3
    while "availability failed" not in caplog.text and time.monotonic() < deadline:
        time.sleep(0.02)
    assert "runner disconnect: publishing availability failed" in caplog.text
    _wait_status(tc, a["id"], "offline")  # the registry was still cleaned up


class _GoneSocket:
    """A peer that vanished: nothing arrives and every send fails."""

    async def receive(self):
        await asyncio.Event().wait()

    async def send_text(self, text):
        raise RuntimeError("socket closed")

    async def close(self, code=1000):
        pass


async def test_failed_welcome_send_ends_serve_quietly(db):
    """agents.updated while the peer is already gone: _serve ends instead of raising RunnerClosed."""
    from app.core.events import Event
    from app.runner.registry import RunnerConn
    from app.runner.router import _serve

    user = await make_user(db)
    conn = RunnerConn(user.id, user.id, _GoneSocket())
    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait(Event(type="agents.updated", user_id=user.id))
    await asyncio.wait_for(_serve(conn, queue, None), 5)
