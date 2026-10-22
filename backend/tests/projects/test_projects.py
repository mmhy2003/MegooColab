import pytest

from app.auth.models import Role
from tests.factories import login, make_team, make_user

DEFAULT_COLUMNS = [
    ("Backlog", "before"),
    ("To Do", "before"),
    ("In Progress", "working"),
    ("In Review", "review"),
    ("Done", "done"),
]


async def _manager_with_team(client, db):
    m = await make_user(db, role=Role.manager)
    team = await make_team(db, m)
    await login(client, m)
    return m, team


async def _create(client, team, key="PAY", **kw):
    return await client.post(
        "/api/projects",
        json={"key": key, "name": kw.get("name", "Payments"), "description": "", "team_ids": [str(team.id)]},
    )


async def test_create_project_creates_default_columns(client, db):
    _, team = await _manager_with_team(client, db)
    r = await _create(client, team)
    assert r.status_code == 201
    assert r.json()["key"] == "PAY" and r.json()["sprints_enabled"] is True
    cols = (await client.get("/api/projects/PAY/columns")).json()
    assert [(c["name"], c["category"]) for c in cols] == DEFAULT_COLUMNS


@pytest.mark.parametrize("key,code", [("P", 422), ("1AB", 422), ("pay", 422), ("TOOLONGKEY1", 422), ("PAY", 201)])
async def test_project_key_validation(client, db, key, code):
    _, team = await _manager_with_team(client, db)
    assert (await _create(client, team, key=key)).status_code == code


async def test_duplicate_key_409(client, db):
    _, team = await _manager_with_team(client, db)
    await _create(client, team)
    assert (await _create(client, team)).status_code == 409


async def test_project_requires_a_team(client, db):
    await _manager_with_team(client, db)
    r = await client.post("/api/projects", json={"key": "PAY", "name": "P", "description": "", "team_ids": []})
    assert r.status_code == 422


async def test_manager_cannot_use_team_they_are_not_in(client, db):
    await _manager_with_team(client, db)
    other_team = await make_team(db)
    assert (await _create(client, other_team)).status_code == 403


async def test_member_cannot_create_project(client, db):
    u = await make_user(db, role=Role.member)
    team = await make_team(db, u)
    await login(client, u)
    assert (await _create(client, team)).status_code == 403


async def test_access_follows_team_membership(client, client_factory, db):
    _, team = await _manager_with_team(client, db)
    await _create(client, team)
    outsider = await make_user(db)
    oc = client_factory()
    await login(oc, outsider)
    assert (await oc.get("/api/projects/PAY")).status_code == 404
    assert (await oc.get("/api/projects")).json() == []
    r = await client.put(f"/api/teams/{team.id}/members", json={"user_ids": [str(u) for u in await _member_ids(client, team)] + [str(outsider.id)]})
    assert r.status_code == 200
    assert (await oc.get("/api/projects/PAY")).status_code == 200
    assert [p["key"] for p in (await oc.get("/api/projects")).json()] == ["PAY"]


async def _member_ids(client, team):
    return [m["id"] for m in (await client.get(f"/api/teams/{team.id}")).json()["members"]]


async def test_project_ref_accepts_uuid(client, db):
    _, team = await _manager_with_team(client, db)
    pid = (await _create(client, team)).json()["id"]
    assert (await client.get(f"/api/projects/{pid}")).json()["key"] == "PAY"


async def test_viewer_cannot_write(client, client_factory, db):
    _, team = await _manager_with_team(client, db)
    await _create(client, team)
    v = await make_user(db, role=Role.viewer)
    await client.put(f"/api/teams/{team.id}/members", json={"user_ids": await _member_ids(client, team) + [str(v.id)]})
    vc = client_factory()
    await login(vc, v)
    assert (await vc.get("/api/projects/PAY")).status_code == 200
    assert (await vc.patch("/api/projects/PAY", json={"name": "X"})).status_code == 403
    assert (await vc.post("/api/projects/PAY/labels", json={"name": "bug", "color": "#ff0000"})).status_code == 403


async def test_manager_outside_teams_cannot_edit(client, client_factory, db):
    _, team = await _manager_with_team(client, db)
    await _create(client, team)
    admin = await make_user(db, role=Role.admin)
    ac = client_factory()
    await login(ac, admin)
    other_manager = await make_user(db, role=Role.manager)
    await ac.put(f"/api/teams/{team.id}/members", json={"user_ids": await _member_ids(client, team)})
    mc = client_factory()
    await login(mc, other_manager)
    assert (await mc.patch("/api/projects/PAY", json={"name": "X"})).status_code == 404
    assert (await ac.patch("/api/projects/PAY", json={"name": "Payments 2", "sprints_enabled": False})).json()["sprints_enabled"] is False


async def test_only_admin_deletes_project(client, client_factory, db):
    _, team = await _manager_with_team(client, db)
    await _create(client, team)
    assert (await client.delete("/api/projects/PAY")).status_code == 403
    admin = await make_user(db, role=Role.admin)
    ac = client_factory()
    await login(ac, admin)
    assert (await ac.delete("/api/projects/PAY")).status_code == 204
    assert (await ac.get("/api/projects/PAY")).status_code == 404


async def test_delete_team_with_projects_409(client, db):
    _, team = await _manager_with_team(client, db)
    await _create(client, team)
    assert (await client.delete(f"/api/teams/{team.id}")).status_code == 409
    detail = (await client.get(f"/api/teams/{team.id}")).json()
    assert [p["key"] for p in detail["projects"]] == ["PAY"]
    assert (await client.get("/api/teams")).json()[0]["project_count"] == 1


async def test_repositories_and_labels_crud(client, db):
    _, team = await _manager_with_team(client, db)
    await _create(client, team)
    r = await client.post("/api/projects/PAY/repositories", json={"name": "api", "url": "https://github.com/acme/api", "provider": "github"})
    assert r.status_code == 201 and r.json()["default_branch"] == "main"
    repo_id = r.json()["id"]
    assert (await client.patch(f"/api/projects/PAY/repositories/{repo_id}", json={"default_branch": "develop"})).json()["default_branch"] == "develop"
    assert len((await client.get("/api/projects/PAY/repositories")).json()) == 1
    assert (await client.delete(f"/api/projects/PAY/repositories/{repo_id}")).status_code == 204

    r = await client.post("/api/projects/PAY/labels", json={"name": "bug", "color": "#FF2A6D"})
    assert r.status_code == 201
    assert (await client.post("/api/projects/PAY/labels", json={"name": "bug", "color": "#000000"})).status_code == 409
    assert (await client.post("/api/projects/PAY/labels", json={"name": "x", "color": "red"})).status_code == 422
    assert [l["name"] for l in (await client.get("/api/projects/PAY/labels")).json()] == ["bug"]
