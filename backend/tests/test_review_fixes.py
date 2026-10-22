"""Regression tests for findings from the whole-branch review."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.auth.models import Role, Session
from tests.factories import login, make_project, make_team, make_user


async def test_lockout_holds_under_parallel_attempts(client_factory, db):
    await make_user(db, email="p@x.io")
    clients = [client_factory() for _ in range(12)]
    await asyncio.gather(
        *[c.post("/api/auth/login", json={"email": "p@x.io", "password": "nope-nope-nope"}) for c in clients]
    )
    r = await clients[0].post("/api/auth/login", json={"email": "p@x.io", "password": "correct-horse-1"})
    assert r.status_code == 423


async def test_session_cookie_reissued_when_session_slides(client, db):
    u = await make_user(db)
    await login(client, u)
    await db.execute(update(Session).values(last_seen_at=datetime.now(UTC) - timedelta(hours=2)))
    await db.commit()
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    assert "megoo_session" in r.headers.get("set-cookie", "")
    r = await client.get("/api/auth/me")  # just slid: no need to re-issue again
    assert "megoo_session" not in r.headers.get("set-cookie", "")


async def test_member_cannot_manage_sprints(client, client_factory, db):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    s = (await client.post("/api/projects/PAY/sprints", json={"name": "S", "goal": "", "start_date": "2026-11-02", "end_date": "2026-11-06"})).json()
    mc = client_factory()
    await login(mc, member)
    r = await mc.post("/api/projects/PAY/sprints", json={"name": "S2", "goal": "", "start_date": "2026-11-02", "end_date": "2026-11-06"})
    assert r.status_code == 403
    assert (await mc.post(f"/api/sprints/{s['id']}/start")).status_code == 403
    assert (await mc.patch(f"/api/sprints/{s['id']}", json={"name": "x"})).status_code == 403
    # members still plan work into sprints
    t = (await mc.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})).json()
    assert (await mc.put(f"/api/tasks/{t['key']}/sprint", json={"sprint_id": s["id"]})).status_code == 200


async def test_links_must_stay_within_project(client, db):
    _, manager, team = await make_project(client, db, "PAY")
    await client.post("/api/projects", json={"key": "SEC", "name": "Secret", "description": "", "team_ids": [str(team.id)]})
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    await client.post("/api/projects/SEC/tasks", json={"title": "secret", "type": "task"})
    r = await client.post("/api/tasks/PAY-1/links", json={"target_key": "SEC-1", "kind": "relates"})
    assert r.status_code == 422 and r.json()["detail"] == "cross_project_link"


async def test_activity_cursor_does_not_skip_same_timestamp_items(client, db):
    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    # one request → several events sharing the transaction's now()
    await client.patch("/api/tasks/PAY-1", json={"title": "b", "priority": "high", "story_points": 3})
    seen = []
    params = {"limit": 1}
    while True:
        page = (await client.get("/api/tasks/PAY-1/activity", params=params)).json()
        if not page:
            break
        seen = page + seen
        params = {"limit": 1, "before": page[0]["at"], "before_id": page[0]["id"]}
    assert len(seen) == 4  # created + 3 field changes
    assert len({i["id"] for i in seen}) == 4


async def test_team_detail_hides_projects_the_viewer_cannot_see(client, client_factory, db):
    _, manager, team = await make_project(client, db, "PAY")
    outsider = await make_user(db)
    oc = client_factory()
    await login(oc, outsider)
    assert (await oc.get(f"/api/teams/{team.id}")).json()["projects"] == []
    assert (await client.get(f"/api/teams/{team.id}")).json()["projects"][0]["key"] == "PAY"
