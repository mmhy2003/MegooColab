"""WebSocket tests run the app in Starlette's TestClient (its own thread + event loop, lifespan on).

Calls on the TestClient are synchronous; test data is prepared beforehand with the async `db` fixture.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth.models import Role
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.events import Event, EventHub, publish
from tests.factories import DEFAULT_PASSWORD, make_team, make_user


def _login(tc: TestClient, user) -> None:
    r = tc.post("/api/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD})
    assert r.status_code == 200, r.text


def _project(tc: TestClient, key: str, team) -> dict:
    r = tc.post("/api/projects", json={"key": key, "name": key, "description": "", "team_ids": [str(team.id)]})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def tc_factory(app):
    """`lifespan=True` runs startup (event hub) — use it for the one client that opens the socket."""
    entered: list[TestClient] = []

    def _make(lifespan: bool = False) -> TestClient:
        c = TestClient(app, headers={"X-Megoo-Client": "web"})
        if lifespan:
            c.__enter__()
            entered.append(c)
        return c

    yield _make
    for c in entered:
        c.__exit__(None, None, None)


async def test_ws_rejects_without_session(tc_factory):
    tc = tc_factory(lifespan=True)
    with pytest.raises(WebSocketDisconnect) as exc:
        with tc.websocket_connect("/api/ws") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


async def test_ws_receives_task_created_for_accessible_project(db, tc_factory):
    manager = await make_user(db, role=Role.manager)
    team = await make_team(db, manager)
    tc = tc_factory(lifespan=True)
    _login(tc, manager)
    project = _project(tc, "PAY", team)
    with tc.websocket_connect("/api/ws") as ws:
        tc.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
        msg = ws.receive_json()
        assert msg["type"] == "task.created" and msg["project_id"] == project["id"]


async def test_ws_does_not_receive_other_projects_events(db, tc_factory):
    m1 = await make_user(db, role=Role.manager)
    m2 = await make_user(db, role=Role.manager)
    t1 = await make_team(db, m1)
    t2 = await make_team(db, m2)
    c1, c2 = tc_factory(), tc_factory(lifespan=True)
    _login(c1, m1)
    _login(c2, m2)
    _project(c1, "PAY", t1)
    ops = _project(c2, "OPS", t2)
    with c2.websocket_connect("/api/ws") as ws:
        c1.post("/api/projects/PAY/tasks", json={"title": "secret", "type": "task"})
        c2.post("/api/projects/OPS/tasks", json={"title": "mine", "type": "task"})
        msg = ws.receive_json()
        assert msg["project_id"] == ops["id"]  # the PAY event was filtered out


async def test_ws_stops_receiving_after_removed_from_team(db, tc_factory):
    manager = await make_user(db, role=Role.manager)
    member = await make_user(db)
    team = await make_team(db, manager, member)
    other_team = await make_team(db, member)
    mc, uc = tc_factory(), tc_factory(lifespan=True)
    _login(mc, manager)
    _login(uc, member)
    _project(mc, "PAY", team)
    admin = await make_user(db, role=Role.admin)
    ac = tc_factory()
    _login(ac, admin)
    own = _project(ac, "OWN", other_team)
    with uc.websocket_connect("/api/ws") as ws:
        mc.post("/api/projects/PAY/tasks", json={"title": "visible", "type": "task"})
        assert ws.receive_json()["type"] == "task.created"
        r = mc.put(f"/api/teams/{team.id}/members", json={"user_ids": [str(manager.id)]})
        assert r.status_code == 200
        assert ws.receive_json() == {"type": "membership.changed", "project_id": None, "task_id": None, "user_id": str(member.id)}
        mc.post("/api/projects/PAY/tasks", json={"title": "hidden", "type": "task"})
        ac.post("/api/projects/OWN/tasks", json={"title": "still visible", "type": "task"})
        msg = ws.receive_json()
        assert msg["project_id"] == own["id"]


async def test_ws_closes_on_deactivation_within_2s(db, tc_factory):
    admin = await make_user(db, role=Role.admin)
    member = await make_user(db)
    ac, uc = tc_factory(), tc_factory(lifespan=True)
    _login(ac, admin)
    _login(uc, member)
    with uc.websocket_connect("/api/ws") as ws:
        started = time.monotonic()
        assert ac.post(f"/api/admin/users/{member.id}/deactivate").status_code == 204
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                ws.receive_json()
        assert exc.value.code == 4401
        assert time.monotonic() - started < 2


async def test_publish_inside_rolled_back_transaction_is_not_delivered():
    hub = EventHub()
    await hub.start(get_settings().database_url)
    q = hub.subscribe()
    try:
        await hub.ready.wait()
        async with SessionLocal() as s:
            await publish(s, Event(type="rolled.back"))
            await s.rollback()
        async with SessionLocal() as s:
            await publish(s, Event(type="committed"))
            await s.commit()
        ev = await asyncio.wait_for(q.get(), timeout=2)
        assert ev.type == "committed"
    finally:
        hub.unsubscribe(q)
        await hub.stop()
