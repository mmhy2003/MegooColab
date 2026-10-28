"""Project status (Active, Finished, Archived): closed projects refuse every write and stay readable."""

import pytest
from sqlalchemy import update

from app.projects.models import Project
from tests.factories import login, make_project, make_user
from tests.mcp.test_mcp import _mint, call, mcp_session


async def close(db, project_key: str, status: str) -> None:
    """Sets a project's status directly (later tests reuse this)."""
    await db.execute(update(Project).where(Project.key == project_key).values(status=status))
    await db.commit()


async def test_new_projects_are_active(client, db):
    p, _m, _t = await make_project(client, db, "PAY")
    assert p["status"] == "active"


@pytest.mark.parametrize("status", ["finished", "archived"])
async def test_closed_projects_refuse_writes_and_allow_reads(client, db, status):
    await make_project(client, db, "PAY")
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "A"})).json()
    await close(db, "PAY", status)
    writes = [
        ("POST", "/api/projects/PAY/tasks", {"title": "B"}),
        ("PATCH", f"/api/tasks/{task['key']}", {"title": "C"}),
        ("POST", f"/api/tasks/{task['key']}/comments", {"body_md": "hi"}),
        ("POST", "/api/projects/PAY/sprints", {"name": "S", "start_date": "2026-11-02", "end_date": "2026-11-13"}),
        ("POST", "/api/projects/PAY/labels", {"name": "x", "color": "#ff0000"}),
        ("PATCH", "/api/projects/PAY", {"name": "Renamed"}),
        ("POST", f"/api/tasks/{task['key']}/workflow/start", None),
    ]
    for method, url, body in writes:
        r = await client.request(method, url, json=body)
        assert (r.status_code, r.json().get("detail")) == (409, "project_closed"), f"{method} {url}: {r.text}"
    assert (await client.get("/api/projects/PAY")).json()["status"] == status
    assert (await client.get(f"/api/tasks/{task['key']}")).status_code == 200
    assert (await client.get("/api/projects/PAY/tasks")).status_code == 200


async def test_outsiders_still_get_404_on_a_closed_project(client, db):
    await make_project(client, db, "PAY")
    await close(db, "PAY", "finished")
    await login(client, await make_user(db))
    assert (await client.post("/api/projects/PAY/tasks", json={"title": "B"})).status_code == 404


async def test_mcp_writes_are_refused_on_a_closed_project(app, client, db, mcp_running):
    await make_project(client, db, "PAY")
    await client.post("/api/projects/PAY/tasks", json={"title": "A"})
    secret = await _mint(client)
    await close(db, "PAY", "finished")
    async with mcp_session(app, secret) as s:
        err, text = await call(s, "update_task", key="PAY-1", title="Changed")
        assert err and "project_closed" in text
        err, text = await call(s, "create_task", project_key="PAY", title="New")
        assert err and "project_closed" in text
        err, _ = await call(s, "get_task", key="PAY-1")
        assert not err


async def test_comments_cannot_be_edited_or_deleted_in_a_closed_project(client, db):
    await make_project(client, db, "PAY")
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "A"})).json()
    comment = (await client.post(f"/api/tasks/{task['key']}/comments", json={"body_md": "hi"})).json()
    await close(db, "PAY", "finished")
    r = await client.patch(f"/api/comments/{comment['id']}", json={"body_md": "changed"})
    assert (r.status_code, r.json()["detail"]) == (409, "project_closed")
    r = await client.delete(f"/api/comments/{comment['id']}")
    assert (r.status_code, r.json()["detail"]) == (409, "project_closed")
