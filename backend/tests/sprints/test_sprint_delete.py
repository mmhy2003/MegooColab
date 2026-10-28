"""Deleting a sprint: its tasks go back to the backlog."""

from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.auth.models import Role
from app.sprints.models import SprintSnapshot
from tests.factories import login, make_project, make_user
from tests.projects.test_project_status import close

SPRINT = {"name": "S1", "start_date": "2026-11-02", "end_date": "2026-11-13"}


async def test_deleting_a_sprint_returns_its_tasks_to_the_backlog(client, db):
    await make_project(client, db, "PAY")
    sprint = (await client.post("/api/projects/PAY/sprints", json=SPRINT)).json()
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "A"})).json()
    assert (await client.put(f"/api/tasks/{task['key']}/sprint", json={"sprint_id": sprint["id"]})).status_code == 200
    assert (await client.post(f"/api/sprints/{sprint['id']}/start")).status_code == 200
    assert await db.scalar(select(func.count()).select_from(SprintSnapshot)) >= 1
    assert (await client.delete(f"/api/sprints/{sprint['id']}")).status_code == 204
    assert (await client.get(f"/api/tasks/{task['key']}")).json()["sprint_id"] is None
    assert (await client.get("/api/projects/PAY/sprints")).json() == []
    assert await db.scalar(select(func.count()).select_from(SprintSnapshot)) == 0
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == "sprint.deleted"))).scalars().all()
    assert [r.data for r in rows] == [{"name": "S1"}]


async def test_members_cannot_delete_sprints_and_closed_projects_refuse(client, db):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    sprint = (await client.post("/api/projects/PAY/sprints", json=SPRINT)).json()
    await login(client, member)
    assert (await client.delete(f"/api/sprints/{sprint['id']}")).status_code == 403
    await close(db, "PAY", "finished")
    await login(client, await make_user(db, role=Role.admin))
    r = await client.delete(f"/api/sprints/{sprint['id']}")
    assert (r.status_code, r.json()["detail"]) == (409, "project_closed")
