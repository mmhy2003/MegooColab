from datetime import date

import pytest

from app.sprints import service as sprint_service
from tests.factories import make_project


@pytest.fixture
def frozen_today(monkeypatch):
    holder = {"d": date(2026, 11, 2)}
    monkeypatch.setattr(sprint_service, "today", lambda: holder["d"])
    return holder


async def _sprint(client, name="Sprint 1", start="2026-11-02", end="2026-11-06"):
    r = await client.post("/api/projects/PAY/sprints", json={"name": name, "goal": "ship", "start_date": start, "end_date": end})
    assert r.status_code == 201, r.text
    return r.json()


async def _task(client, title, points=None, sprint=None):
    t = (await client.post("/api/projects/PAY/tasks", json={"title": title, "type": "task", "story_points": points})).json()
    if sprint:
        r = await client.put(f"/api/tasks/{t['key']}/sprint", json={"sprint_id": sprint["id"]})
        assert r.status_code == 200, r.text
    return t


async def _done_col(client):
    return (await client.get("/api/projects/PAY/columns")).json()[-1]["id"]


async def test_only_one_active_sprint(client, db, frozen_today):
    await make_project(client, db)
    s1 = await _sprint(client)
    s2 = await _sprint(client, "Sprint 2")
    assert (await client.post(f"/api/sprints/{s1['id']}/start")).json()["state"] == "active"
    r = await client.post(f"/api/sprints/{s2['id']}/start")
    assert r.status_code == 409 and r.json()["detail"] == "active_sprint_exists"


async def test_sprint_filter_active_and_task_sprint_assignment(client, db, frozen_today):
    await make_project(client, db)
    s1 = await _sprint(client)
    a = await _task(client, "a", 3, s1)
    await _task(client, "b", 1)
    await client.post(f"/api/sprints/{s1['id']}/start")
    keys = [t["key"] for t in (await client.get("/api/projects/PAY/tasks", params={"sprint": "active"})).json()]
    assert keys == [a["key"]]
    epic = (await client.post("/api/projects/PAY/tasks", json={"title": "e", "type": "epic"})).json()
    r = await client.put(f"/api/tasks/{epic['key']}/sprint", json={"sprint_id": s1["id"]})
    assert r.status_code == 422


async def test_burndown_forward_fills_and_ideal_line(client, db, frozen_today):
    await make_project(client, db)
    s = await _sprint(client)  # 2026-11-02 .. 2026-11-06
    a = await _task(client, "a", 5, s)
    await _task(client, "b", 3, s)
    await client.post(f"/api/sprints/{s['id']}/start")  # committed 8, snapshot day 1
    frozen_today["d"] = date(2026, 11, 4)
    await client.post(f"/api/tasks/{a['key']}/move", json={"column_id": await _done_col(client)})  # remaining 3 on day 3
    burndown = (await client.get(f"/api/sprints/{s['id']}/burndown")).json()
    assert burndown == [
        {"day": "2026-11-02", "remaining_points": 8, "ideal_points": 8.0},
        {"day": "2026-11-03", "remaining_points": 8, "ideal_points": 6.0},
        {"day": "2026-11-04", "remaining_points": 3, "ideal_points": 4.0},
    ]


async def test_complete_moves_open_tasks_to_backlog(client, db, frozen_today):
    await make_project(client, db)
    s = await _sprint(client)
    a = await _task(client, "a", 5, s)
    b = await _task(client, "b", 2, s)
    await client.post(f"/api/sprints/{s['id']}/start")
    await client.post(f"/api/tasks/{a['key']}/move", json={"column_id": await _done_col(client)})
    r = await client.post(f"/api/sprints/{s['id']}/complete", json={"move_open_to": "backlog"})
    assert r.status_code == 200
    assert r.json()["state"] == "completed" and r.json()["completed_points"] == 5
    assert (await client.get(f"/api/tasks/{b['key']}")).json()["sprint_id"] is None
    assert (await client.get(f"/api/tasks/{a['key']}")).json()["sprint_id"] == s["id"]


async def test_complete_moves_open_tasks_to_next_sprint(client, db, frozen_today):
    await make_project(client, db)
    s1 = await _sprint(client)
    s2 = await _sprint(client, "Sprint 2", "2026-11-09", "2026-11-13")
    b = await _task(client, "b", 2, s1)
    await client.post(f"/api/sprints/{s1['id']}/start")
    r = await client.post(f"/api/sprints/{s1['id']}/complete", json={"move_open_to": s2["id"]})
    assert r.status_code == 200
    assert (await client.get(f"/api/tasks/{b['key']}")).json()["sprint_id"] == s2["id"]


async def test_velocity_lists_completed_sprints_newest_last(client, db, frozen_today):
    await make_project(client, db)
    for i, pts in enumerate([3, 8], start=1):
        s = await _sprint(client, f"Sprint {i}")
        t = await _task(client, f"t{i}", pts, s)
        await client.post(f"/api/sprints/{s['id']}/start")
        await client.post(f"/api/tasks/{t['key']}/move", json={"column_id": await _done_col(client)})
        await client.post(f"/api/sprints/{s['id']}/complete", json={"move_open_to": "backlog"})
    v = (await client.get("/api/projects/PAY/velocity")).json()
    assert [(x["name"], x["committed_points"], x["completed_points"]) for x in v] == [("Sprint 1", 3, 3), ("Sprint 2", 8, 8)]


async def test_sprints_disabled_409(client, db):
    await make_project(client, db)
    await client.patch("/api/projects/PAY", json={"sprints_enabled": False})
    r = await client.post("/api/projects/PAY/sprints", json={"name": "S", "goal": "", "start_date": "2026-11-02", "end_date": "2026-11-06"})
    assert r.status_code == 409 and r.json()["detail"] == "sprints_disabled"
    assert (await client.get("/api/projects/PAY/sprints")).status_code == 409


async def test_end_before_start_422(client, db):
    await make_project(client, db)
    r = await client.post("/api/projects/PAY/sprints", json={"name": "S", "goal": "", "start_date": "2026-11-06", "end_date": "2026-11-02"})
    assert r.status_code == 422
