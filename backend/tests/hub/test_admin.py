from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import Role
from tests.factories import login, make_team, make_user


async def _as(client, db, role=Role.member):
    u = await make_user(db, role=role)
    await login(client, u)
    return u


SPEC = {"transport": "http", "url": "https://mcp.example.com/mcp", "headers": []}


async def _tool(client, name):
    r = await client.post("/api/hub/tools", json={"kind": "mcp", "name": name, "spec": SPEC})
    assert r.status_code == 201, r.text
    return r.json()


async def test_admin_list_only_shared(client, client_factory, db):
    owner = await _as(client, db)
    private = await _tool(client, "private")
    shared = await _tool(client, "shared")
    team = await make_team(db, owner)
    await client.put(f"/api/hub/tools/{shared['id']}/sharing", json={"teams": [str(team.id)]})
    admin = client_factory()
    await _as(admin, db, Role.admin)
    rows = (await admin.get("/api/admin/hub/tools")).json()
    assert [r["name"] for r in rows] == ["shared"]
    assert rows[0]["sharing"]["teams"] == [{"id": str(team.id), "name": team.name}]
    assert rows[0]["owner"]["id"] == str(owner.id)
    assert (await admin.get(f"/api/hub/tools/{private['id']}")).status_code == 404
    assert (await admin.get("/api/admin/hub/tools", params={"q": "nope"})).json() == []


async def test_member_forbidden(client, db):
    await _as(client, db)
    t = await _tool(client, "x")
    assert (await client.get("/api/admin/hub/tools")).status_code == 403
    assert (await client.post(f"/api/admin/hub/tools/{t['id']}/unshare")).status_code == 403
    assert (await client.post(f"/api/admin/hub/tools/{t['id']}/remove")).status_code == 403


async def test_unshare(client, client_factory, db):
    owner = await _as(client, db)
    t = await _tool(client, "x")
    viewer = client_factory()
    v = await _as(viewer, db)
    team = await make_team(db, owner, v)
    await client.put(f"/api/hub/tools/{t['id']}/sharing", json={"teams": [str(team.id)], "everyone": True})
    admin = client_factory()
    a = await _as(admin, db, Role.admin)
    assert (await admin.post(f"/api/admin/hub/tools/{t['id']}/unshare")).status_code == 204
    assert (await viewer.get("/api/hub/tools", params={"shelf": "shared"})).json() == []
    assert (await viewer.get("/api/hub/tools", params={"shelf": "everyone"})).json() == []
    assert (await client.get(f"/api/hub/tools/{t['id']}")).json()["sharing"] == {
        "teams": [], "users": [], "everyone": False}
    row = (await db.execute(select(AuditLog).where(AuditLog.action == "hub.tool_unshared"))).scalar_one()
    assert row.actor_user_id == a.id and row.data["name"] == "x"


async def test_remove_marks_live_copies_only(client, client_factory, db):
    owner = await _as(client, db)
    t = await _tool(client, "x")
    b, c = client_factory(), client_factory()
    bu, cu = await _as(b, db), await _as(c, db)
    team = await make_team(db, owner, bu, cu)
    await client.put(f"/api/hub/tools/{t['id']}/sharing", json={"teams": [str(team.id)]})
    b_copy = (await b.post(f"/api/hub/tools/{t['id']}/copy")).json()
    c_copy = (await c.post(f"/api/hub/tools/{t['id']}/copy")).json()
    await c.post(f"/api/hub/tools/{c_copy['id']}/own")
    admin = client_factory()
    await _as(admin, db, Role.admin)
    assert (await admin.post(f"/api/admin/hub/tools/{t['id']}/remove")).status_code == 204
    src = (await client.get(f"/api/hub/tools/{t['id']}")).json()
    assert src["removed"] is True and src["can_edit"] is False
    got_b = (await b.get(f"/api/hub/tools/{b_copy['id']}")).json()
    assert got_b["removed"] is True and got_b["rev"] > b_copy["rev"]
    assert (await c.get(f"/api/hub/tools/{c_copy['id']}")).json()["removed"] is False
    r = await b.patch(f"/api/hub/tools/{b_copy['id']}", json={"read_only_safe": True})
    assert r.status_code == 409 and r.json()["detail"] == "hub_removed"
    for path in ("own", "update"):
        assert (await b.post(f"/api/hub/tools/{b_copy['id']}/{path}")).json()["detail"] == "hub_removed"
    r = await client.put(f"/api/hub/tools/{t['id']}/sharing", json={"everyone": True})
    assert r.status_code == 409 and r.json()["detail"] == "hub_removed"
    assert (await b.delete(f"/api/hub/tools/{b_copy['id']}")).status_code == 204
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "hub.tool_removed"))).scalar_one()


async def test_removed_hidden_from_shelves(client, client_factory, db):
    await _as(client, db)
    t = await _tool(client, "x")
    await client.put(f"/api/hub/tools/{t['id']}/sharing", json={"everyone": True})
    viewer, admin = client_factory(), client_factory()
    await _as(viewer, db)
    await _as(admin, db, Role.admin)
    await admin.post(f"/api/admin/hub/tools/{t['id']}/remove")
    assert (await viewer.get("/api/hub/tools", params={"shelf": "everyone"})).json() == []
    assert (await viewer.get(f"/api/hub/tools/{t['id']}")).status_code == 404
    assert (await viewer.post(f"/api/hub/tools/{t['id']}/copy")).status_code == 404
    mine = (await client.get("/api/hub/tools", params={"shelf": "mine"})).json()
    assert mine[0]["removed"] is True
    assert (await admin.get("/api/admin/hub/tools")).json() == []
