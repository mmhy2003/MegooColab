import asyncio

from app.auth.models import Role
from tests.factories import login, make_project, make_team, make_user


async def _task(client, title="t", **kw):
    r = await client.post("/api/projects/PAY/tasks", json={"title": title, "type": kw.pop("type", "task"), **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_concurrent_creates_get_unique_sequential_numbers(client, client_factory, db):
    members = [await make_user(db) for _ in range(3)]
    await make_project(client, db, "PAY", *members)
    clients = [client]
    for m in members:
        c = client_factory()
        await login(c, m)
        clients.append(c)
    results = await asyncio.gather(
        *[c.post("/api/projects/PAY/tasks", json={"title": f"t{i}", "type": "task"}) for i, c in enumerate(clients * 5)]
    )
    assert all(r.status_code == 201 for r in results), [r.text for r in results if r.status_code != 201]
    numbers = sorted(r.json()["number"] for r in results)
    assert numbers == list(range(1, 21))


async def test_key_format_and_get_by_key(client, db):
    await make_project(client, db)
    t = await _task(client, "Sync orders")
    assert t["key"] == "PAY-1"
    r = await client.get("/api/tasks/PAY-1")
    assert r.status_code == 200 and r.json()["title"] == "Sync orders"
    assert (await client.get("/api/tasks/pay-1")).status_code == 200
    assert (await client.get("/api/tasks/PAY-99")).status_code == 404
    assert (await client.get("/api/tasks/garbage")).status_code == 404


async def test_default_column_is_first_before_column(client, db):
    await make_project(client, db)
    cols = (await client.get("/api/projects/PAY/columns")).json()
    t = await _task(client)
    assert t["column_id"] == cols[0]["id"] and t["column_category"] == "before"
    assert t["priority"] == "medium"


async def test_created_in_done_column_is_completed(client, db):
    await make_project(client, db)
    done = (await client.get("/api/projects/PAY/columns")).json()[-1]
    t = await _task(client, column_id=done["id"])
    assert t["completed_at"] is not None


async def test_tasks_append_to_end_of_column(client, db):
    await make_project(client, db)
    a = await _task(client, "a")
    b = await _task(client, "b")
    assert b["position"] > a["position"]


async def test_subtask_requires_non_epic_parent(client, db):
    await make_project(client, db)
    epic = await _task(client, "E", type="epic")
    r = await client.post("/api/projects/PAY/tasks", json={"title": "s", "type": "subtask"})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_parent"
    r = await client.post("/api/projects/PAY/tasks", json={"title": "s", "type": "subtask", "parent_id": epic["id"]})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_parent"
    story = await _task(client, "S", type="story", parent_id=epic["id"])
    sub = await _task(client, "sub", type="subtask", parent_id=story["id"])
    r = await client.post("/api/projects/PAY/tasks", json={"title": "s2", "type": "subtask", "parent_id": sub["id"]})
    assert r.status_code == 422
    assert (await client.get("/api/tasks/PAY-2")).json()["subtask_count"] == 1


async def test_epic_cannot_have_parent(client, db):
    await make_project(client, db)
    epic = await _task(client, "E", type="epic")
    r = await client.post("/api/projects/PAY/tasks", json={"title": "E2", "type": "epic", "parent_id": epic["id"]})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_parent"
    task = await _task(client, "T")
    r = await client.post("/api/projects/PAY/tasks", json={"title": "x", "type": "story", "parent_id": task["id"]})
    assert r.status_code == 422


async def test_parent_must_be_same_project(client, client_factory, db):
    _, manager, team = await make_project(client, db, "PAY")
    other = await _task(client, "E", type="epic")
    r = await client.post("/api/projects", json={"key": "OPS", "name": "Ops", "description": "", "team_ids": [str(team.id)]})
    assert r.status_code == 201
    r = await client.post("/api/projects/OPS/tasks", json={"title": "x", "type": "story", "parent_id": other["id"]})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_parent"


async def test_assignee_without_access_422(client, db):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    outsider = await make_user(db)
    r = await client.post("/api/projects/PAY/tasks", json={"title": "x", "type": "task", "assignee_user_id": str(outsider.id)})
    assert r.status_code == 422 and r.json()["detail"] == "assignee_no_access"
    t = await _task(client, "x", assignee_user_id=str(member.id))
    assert t["assignee_user_id"] == str(member.id)


async def test_update_task_fields_and_labels(client, db):
    await make_project(client, db)
    label = (await client.post("/api/projects/PAY/labels", json={"name": "bug", "color": "#FF0000"})).json()
    t = await _task(client)
    r = await client.patch(f"/api/tasks/{t['key']}", json={"title": "New", "story_points": 5, "priority": "high", "label_ids": [label["id"]], "due_date": "2026-11-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "New" and body["story_points"] == 5 and body["priority"] == "high"
    assert [l["name"] for l in body["labels"]] == ["bug"] and body["due_date"] == "2026-11-01"
    r = await client.patch(f"/api/tasks/{t['key']}", json={"story_points": None})
    assert r.json()["story_points"] is None and r.json()["title"] == "New"


async def test_filters(client, db):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    label = (await client.post("/api/projects/PAY/labels", json={"name": "bug", "color": "#FF0000"})).json()
    epic = await _task(client, "Epic", type="epic")
    a = await _task(client, "Alpha sync", parent_id=epic["id"], assignee_user_id=str(member.id))
    b = await _task(client, "Beta", label_ids=[label["id"]])

    async def keys(**params):
        return sorted(t["key"] for t in (await client.get("/api/projects/PAY/tasks", params=params)).json())

    assert await keys(assignee=str(member.id)) == [a["key"]]
    assert await keys(label=label["id"]) == [b["key"]]
    assert await keys(epic=epic["id"]) == [a["key"]]
    assert await keys(q="sync") == [a["key"]]
    assert await keys(type="epic") == [epic["key"]]
    assert await keys(sprint="backlog") == sorted([epic["key"], a["key"], b["key"]])


async def test_viewer_cannot_create(client, client_factory, db):
    viewer = await make_user(db, role=Role.viewer)
    await make_project(client, db, "PAY", viewer)
    vc = client_factory()
    await login(vc, viewer)
    assert (await vc.post("/api/projects/PAY/tasks", json={"title": "x", "type": "task"})).status_code == 403
    assert (await vc.get("/api/projects/PAY/tasks")).status_code == 200


async def test_delete_task_rules(client, client_factory, db):
    member = await make_user(db)
    other = await make_user(db)
    await make_project(client, db, "PAY", member, other)
    mc = client_factory()
    await login(mc, member)
    epic = (await mc.post("/api/projects/PAY/tasks", json={"title": "E", "type": "epic"})).json()
    story = (await mc.post("/api/projects/PAY/tasks", json={"title": "S", "type": "story", "parent_id": epic["id"]})).json()
    sub = (await mc.post("/api/projects/PAY/tasks", json={"title": "sub", "type": "subtask", "parent_id": story["id"]})).json()
    oc = client_factory()
    await login(oc, other)
    assert (await oc.delete(f"/api/tasks/{story['key']}")).status_code == 403
    assert (await mc.delete(f"/api/tasks/{epic['key']}")).status_code == 204
    assert (await mc.get(f"/api/tasks/{story['key']}")).json()["parent_id"] is None
    assert (await client.delete(f"/api/tasks/{story['key']}")).status_code == 204  # manager
    assert (await client.get(f"/api/tasks/{sub['key']}")).status_code == 404


async def test_delete_column_with_tasks_requires_move_to(client, db):
    await make_project(client, db)
    cols = {c["name"]: c for c in (await client.get("/api/projects/PAY/columns")).json()}
    t = await _task(client, column_id=cols["In Review"]["id"])
    assert {c["name"]: c["task_count"] for c in (await client.get("/api/projects/PAY/columns")).json()}["In Review"] == 1
    r = await client.delete(f"/api/projects/PAY/columns/{cols['In Review']['id']}")
    assert r.status_code == 409 and r.json()["detail"] == "move_to_required"
    r = await client.delete(f"/api/projects/PAY/columns/{cols['In Review']['id']}", params={"move_to": cols["Done"]["id"]})
    assert r.status_code == 204
    moved = (await client.get(f"/api/tasks/{t['key']}")).json()
    assert moved["column_id"] == cols["Done"]["id"] and moved["completed_at"] is not None
