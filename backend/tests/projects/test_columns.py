from app.auth.models import Role
from tests.factories import login, make_team, make_user


async def _project(client, db):
    m = await make_user(db, role=Role.manager)
    team = await make_team(db, m)
    await login(client, m)
    r = await client.post("/api/projects", json={"key": "PAY", "name": "Payments", "description": "", "team_ids": [str(team.id)]})
    assert r.status_code == 201
    return {c["name"]: c for c in (await client.get("/api/projects/PAY/columns")).json()}


async def test_add_column_appends(client, db):
    await _project(client, db)
    r = await client.post("/api/projects/PAY/columns", json={"name": "Blocked", "category": "working"})
    assert r.status_code == 201
    names = [c["name"] for c in (await client.get("/api/projects/PAY/columns")).json()]
    assert names[-1] == "Blocked"


async def test_cannot_delete_last_done_column(client, db):
    cols = await _project(client, db)
    r = await client.delete(f"/api/projects/PAY/columns/{cols['Done']['id']}")
    assert r.status_code == 409 and r.json()["detail"] == "last_before_or_done_column"


async def test_can_delete_one_of_two_before_columns(client, db):
    cols = await _project(client, db)
    assert (await client.delete(f"/api/projects/PAY/columns/{cols['Backlog']['id']}")).status_code == 204
    r = await client.delete(f"/api/projects/PAY/columns/{cols['To Do']['id']}")
    assert r.status_code == 409


async def test_cannot_recategorize_last_before_column(client, db):
    cols = await _project(client, db)
    await client.delete(f"/api/projects/PAY/columns/{cols['Backlog']['id']}")
    r = await client.patch(f"/api/projects/PAY/columns/{cols['To Do']['id']}", json={"category": "working"})
    assert r.status_code == 409 and r.json()["detail"] == "last_before_or_done_column"
    r = await client.patch(f"/api/projects/PAY/columns/{cols['To Do']['id']}", json={"name": "Ready"})
    assert r.status_code == 200 and r.json()["name"] == "Ready"


async def test_reorder_columns(client, db):
    cols = await _project(client, db)
    order = [cols[n]["id"] for n in ["To Do", "Backlog", "In Progress", "In Review", "Done"]]
    r = await client.put("/api/projects/PAY/columns/order", json={"column_ids": order})
    assert r.status_code == 200
    assert [c["id"] for c in (await client.get("/api/projects/PAY/columns")).json()] == order


async def test_reorder_must_list_every_column(client, db):
    cols = await _project(client, db)
    r = await client.put("/api/projects/PAY/columns/order", json={"column_ids": [cols["Done"]["id"]]})
    assert r.status_code == 422
