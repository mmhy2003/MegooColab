from app.auth.models import Role
from tests.factories import login, make_user


async def _as(client, db, role):
    u = await make_user(db, role=role)
    await login(client, u)
    return u


async def test_manager_creates_team_and_is_member(client, db):
    m = await _as(client, db, Role.manager)
    r = await client.post("/api/teams", json={"name": "Core", "description": "Core platform"})
    assert r.status_code == 201
    team_id = r.json()["id"]
    detail = (await client.get(f"/api/teams/{team_id}")).json()
    assert [x["id"] for x in detail["members"]] == [str(m.id)]
    listed = (await client.get("/api/teams")).json()
    assert listed[0]["name"] == "Core" and listed[0]["member_count"] == 1 and listed[0]["project_count"] == 0


async def test_admin_creates_team_without_joining(client, db):
    await _as(client, db, Role.admin)
    team_id = (await client.post("/api/teams", json={"name": "Ops"})).json()["id"]
    assert (await client.get(f"/api/teams/{team_id}")).json()["members"] == []


async def test_duplicate_team_name_409(client, db):
    await _as(client, db, Role.admin)
    await client.post("/api/teams", json={"name": "Ops"})
    assert (await client.post("/api/teams", json={"name": "Ops"})).status_code == 409


async def test_member_cannot_create_team(client, db):
    await _as(client, db, Role.member)
    assert (await client.post("/api/teams", json={"name": "Nope"})).status_code == 403


async def test_manager_cannot_edit_team_they_are_not_in(client, client_factory, db):
    await _as(client, db, Role.admin)
    team_id = (await client.post("/api/teams", json={"name": "Ops"})).json()["id"]
    other = client_factory()
    await _as(other, db, Role.manager)
    assert (await other.patch(f"/api/teams/{team_id}", json={"name": "Mine"})).status_code == 403
    assert (await other.put(f"/api/teams/{team_id}/members", json={"user_ids": []})).status_code == 403
    assert (await other.delete(f"/api/teams/{team_id}")).status_code == 403


async def test_replace_members(client, db):
    m = await _as(client, db, Role.manager)
    a = await make_user(db)
    b = await make_user(db)
    team_id = (await client.post("/api/teams", json={"name": "Core"})).json()["id"]
    r = await client.put(f"/api/teams/{team_id}/members", json={"user_ids": [str(m.id), str(a.id), str(b.id)]})
    assert r.status_code == 200
    r = await client.put(f"/api/teams/{team_id}/members", json={"user_ids": [str(m.id), str(b.id)]})
    ids = {x["id"] for x in r.json()["members"]}
    assert ids == {str(m.id), str(b.id)}


async def test_replace_members_unknown_user_422(client, db):
    await _as(client, db, Role.admin)
    team_id = (await client.post("/api/teams", json={"name": "Core"})).json()["id"]
    r = await client.put(f"/api/teams/{team_id}/members", json={"user_ids": ["00000000-0000-0000-0000-000000000000"]})
    assert r.status_code == 422


async def test_edit_and_delete_team(client, db):
    await _as(client, db, Role.manager)
    team_id = (await client.post("/api/teams", json={"name": "Core"})).json()["id"]
    r = await client.patch(f"/api/teams/{team_id}", json={"name": "Core Platform", "description": "d"})
    assert r.status_code == 200 and r.json()["name"] == "Core Platform"
    assert (await client.delete(f"/api/teams/{team_id}")).status_code == 204
    assert (await client.get(f"/api/teams/{team_id}")).status_code == 404
