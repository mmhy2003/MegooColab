import uuid

import pytest
from sqlalchemy import select, update

from app.tasks.branches import valid_branch_name
from app.tasks.models import Task, TaskEvent
from app.workflow.models import Driver, TaskWorkflow, WorkflowStatus
from tests.factories import make_project


async def _task(client, **kw):
    r = await client.post("/api/projects/PAY/tasks", json={"title": "t", "type": "task", **kw})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("name", ["main", "develop", "feature/x", "release/1.2"])
def test_branch_name_rules_valid(name):
    assert valid_branch_name(name)


@pytest.mark.parametrize("name", [
    "", "main..x", "-x", "a b", "x.lock", "x/", "/x", "a//b", "@", "a@{b", "x~1", "x^", "x:y", "x?", "x*", "x[",
    "x\\y", ".x", "a/.b", "x.", "a\x01b", "a" * 201,
])
def test_branch_name_rules_invalid(name):
    assert not valid_branch_name(name)


async def test_branch_from_set_and_cleared(client, db):
    await make_project(client, db)
    t = await _task(client, branch_from=" main ")
    assert t["branch_from"] == "main" and t["branch_from_locked"] is False
    assert t["start_branch"] is None and t["back_merge_into"] is None
    r = await client.patch(f"/api/tasks/{t['key']}", json={"branch_from": "hotfix-base"})
    assert r.status_code == 200 and r.json()["branch_from"] == "hotfix-base"
    events = (await db.execute(select(TaskEvent).where(TaskEvent.kind == "field_changed"))).scalars().all()
    assert {"field": "branch_from", "from": "main", "to": "hotfix-base"} in [e.data for e in events]
    r = await client.patch(f"/api/tasks/{t['key']}", json={"branch_from": ""})
    assert r.status_code == 200 and r.json()["branch_from"] is None


async def test_invalid_branch_from_422(client, db):
    await make_project(client, db)
    t = await _task(client)
    r = await client.patch(f"/api/tasks/{t['key']}", json={"branch_from": "main..x"})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_branch_name"
    r = await client.post("/api/projects/PAY/tasks", json={"title": "t", "branch_from": "-x"})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_branch_name"


async def test_branch_from_locked_once_started(client, db):
    await make_project(client, db)
    t = await _task(client, branch_from="main")
    await db.execute(update(Task).where(Task.id == uuid.UUID(t["id"])).values(start_branch="main"))
    await db.commit()
    got = (await client.get(f"/api/tasks/{t['key']}")).json()
    assert got["branch_from_locked"] is True and got["start_branch"] == "main"
    r = await client.patch(f"/api/tasks/{t['key']}", json={"branch_from": "develop"})
    assert r.status_code == 409 and r.json()["detail"] == "branch_from_locked"
    r = await client.patch(f"/api/tasks/{t['key']}", json={"branch_from": "main", "title": "renamed"})
    assert r.status_code == 200 and r.json()["title"] == "renamed"  # an unchanged value is not refused


@pytest.mark.parametrize(("state", "code"), [(WorkflowStatus.running, 409), (WorkflowStatus.idle, 200)])
async def test_branch_from_locked_for_started_connect_only(client, db, state, code):
    await make_project(client, db)
    t = await _task(client)
    db.add(TaskWorkflow(task_id=uuid.UUID(t["id"]), driver=Driver.connect_only, status=state))
    await db.commit()
    r = await client.patch(f"/api/tasks/{t['key']}", json={"branch_from": "main"})
    assert r.status_code == code, r.text


async def test_repository_default_branch_is_a_valid_branch_name(client, db):
    await make_project(client, db)
    base = {"name": "pay", "url": "https://github.com/acme/pay", "provider": "github"}
    for bad in ("", "  ", "develop..x", "-x"):
        r = await client.post("/api/projects/PAY/repositories", json={**base, "default_branch": bad})
        assert r.status_code == 422 and r.json()["detail"] == "invalid_branch_name", (bad, r.text)
    r = await client.post("/api/projects/PAY/repositories", json={**base, "default_branch": " develop "})
    assert r.status_code == 201 and r.json()["default_branch"] == "develop"
    repo_id = r.json()["id"]
    r = await client.patch(f"/api/projects/PAY/repositories/{repo_id}", json={"default_branch": "a b"})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_branch_name"
    r = await client.patch(f"/api/projects/PAY/repositories/{repo_id}", json={"default_branch": "main"})
    assert r.status_code == 200 and r.json()["default_branch"] == "main"
