from sqlalchemy import delete, select

from app.audit.models import AuditLog
from app.auth.models import Role
from app.teams.models import TeamMember
from tests.factories import login, make_team, make_user
from tests.org.test_org_settings import _setup_org

SECRET = "Bearer sk-live-abcdef123456"


async def _as(client, db, role=Role.member):
    u = await make_user(db, role=role)
    await login(client, u)
    return u


def _http(name="ctx", **spec):
    return {
        "kind": "mcp",
        "name": name,
        "spec": {
            "transport": "http",
            "url": "https://mcp.example.com/mcp",
            "headers": [{"name": "Authorization", "secret": True}],
        }
        | spec,
    }


async def _tool(client, name="ctx", **spec):
    r = await client.post("/api/hub/tools", json=_http(name, **spec))
    assert r.status_code == 201, r.text
    return r.json()


async def _share(client, tid, teams=(), users=(), everyone=False):
    return await client.put(
        f"/api/hub/tools/{tid}/sharing",
        json={"teams": [str(t) for t in teams], "users": [str(u) for u in users], "everyone": everyone},
    )


async def _shelf(client, shelf, q=None):
    r = await client.get("/api/hub/tools", params={"shelf": shelf} | ({"q": q} if q else {}))
    assert r.status_code == 200, r.text
    return [t["name"] for t in r.json()]


async def test_share_with_team_shows_on_shared_shelf(client, client_factory, db):
    owner = await _as(client, db)
    t = await _tool(client)
    await client.put(f"/api/hub/tools/{t['id']}/secrets", json={"values": {"Authorization": SECRET}})
    other, stranger = client_factory(), client_factory()
    member = await _as(other, db)
    await _as(stranger, db)
    team = await make_team(db, owner, member)
    r = await _share(client, t["id"], teams=[team.id])
    assert r.status_code == 200, r.text
    assert r.json()["sharing"]["teams"] == [{"id": str(team.id), "name": team.name}]
    assert await _shelf(other, "shared") == ["ctx"]
    assert await _shelf(stranger, "shared") == []
    got = await other.get(f"/api/hub/tools/{t['id']}")
    assert got.status_code == 200
    assert got.json()["secrets"] == [{"name": "Authorization", "set": False}]
    assert got.json()["sharing"] is None and got.json()["can_edit"] is False
    assert SECRET not in got.text
    assert (await stranger.get(f"/api/hub/tools/{t['id']}")).status_code == 404
    assert (await other.patch(f"/api/hub/tools/{t['id']}", json={"description": "x"})).status_code == 403


async def test_left_team_loses_access(client, client_factory, db):
    owner = await _as(client, db)
    t = await _tool(client)
    other = client_factory()
    member = await _as(other, db)
    team = await make_team(db, owner, member)
    await _share(client, t["id"], teams=[team.id])
    await db.execute(delete(TeamMember).where(TeamMember.user_id == member.id))
    await db.commit()
    assert await _shelf(other, "shared") == []
    assert (await other.get(f"/api/hub/tools/{t['id']}")).status_code == 404


async def test_share_with_person_and_everyone(client, client_factory, db):
    await _as(client, db)
    t = await _tool(client)
    friend_client, someone_client = client_factory(), client_factory()
    friend = await _as(friend_client, db)
    await _as(someone_client, db)
    r = await _share(client, t["id"], users=[friend.id])
    assert r.json()["sharing"]["users"] == [{"id": str(friend.id), "name": friend.name}]
    assert await _shelf(friend_client, "shared") == ["ctx"]
    assert await _shelf(someone_client, "everyone") == []
    await _share(client, t["id"], everyone=True)
    assert await _shelf(someone_client, "everyone") == ["ctx"]
    assert await _shelf(friend_client, "shared") == []  # the person share was replaced
    assert await _shelf(client, "everyone") == []  # never your own


async def test_mine_shelf_and_search(client, db):
    await _as(client, db)
    await _tool(client, "alpha")
    await _tool(client, "beta")
    assert await _shelf(client, "mine") == ["alpha", "beta"]
    assert await _shelf(client, "mine", q="ALP") == ["alpha"]


async def test_everyone_off_hides_and_refuses(client, client_factory, db):
    await _setup_org(db)
    await _as(client, db)
    t = await _tool(client)
    await _share(client, t["id"], everyone=True)
    admin_client, viewer = client_factory(), client_factory()
    await _as(admin_client, db, Role.admin)
    await _as(viewer, db)
    settings = (await admin_client.get("/api/admin/settings")).json()
    assert settings["hub"] == {"share_everyone": True}
    r = await admin_client.put("/api/admin/settings", json=settings | {"hub": {"share_everyone": False}})
    assert r.status_code == 200 and r.json()["hub"] == {"share_everyone": False}
    assert await _shelf(viewer, "everyone") == []
    assert (await viewer.get(f"/api/hub/tools/{t['id']}")).status_code == 404
    t2 = await _tool(client, "two")
    r = await _share(client, t2["id"], everyone=True)
    assert r.status_code == 409 and r.json()["detail"] == "hub_everyone_off"
    await admin_client.put("/api/admin/settings", json=settings)
    assert await _shelf(viewer, "everyone") == ["ctx"]


async def test_admin_settings_hub_block_kept_when_absent(client, db):
    await _setup_org(db)
    await _as(client, db, Role.admin)
    settings = (await client.get("/api/admin/settings")).json()
    await client.put("/api/admin/settings", json=settings | {"hub": {"share_everyone": False}})
    body = {k: v for k, v in settings.items() if k != "hub"}
    assert (await client.put("/api/admin/settings", json=body)).json()["hub"] == {"share_everyone": False}


async def test_flagged_values_block_sharing(client, client_factory, db):
    await _as(client, db)
    spec = {"transport": "stdio", "command": {"command": "npx", "args": ["pkg", "sk-live1234567890"]}, "headers": []}
    t = (await client.post("/api/hub/tools", json={"kind": "mcp", "name": "s", "spec": spec})).json()
    assert t["flagged"] == ["args[1]"]
    r = await _share(client, t["id"], everyone=True)
    assert r.status_code == 409 and r.json()["detail"] == "hub_flagged_values"
    assert (await _share(client, t["id"])).status_code == 200  # only me: nothing goes out
    r = await client.patch(f"/api/hub/tools/{t['id']}", json={"spec": spec | {"acknowledged": ["args[1]"]}})
    assert r.json()["flagged"] == []
    assert (await _share(client, t["id"], everyone=True)).status_code == 200


async def test_share_with_non_member_team_403(client, db):
    await _as(client, db)
    t = await _tool(client)
    team = await make_team(db)
    r = await _share(client, t["id"], teams=[team.id])
    assert r.status_code == 403 and r.json()["detail"] == "hub_team_not_member"


async def test_admin_may_share_with_any_team(client, db):
    await _as(client, db, Role.admin)
    t = await _tool(client)
    team = await make_team(db)
    assert (await _share(client, t["id"], teams=[team.id])).status_code == 200


async def test_share_with_self_or_unknown_422(client, db):
    me = await _as(client, db)
    t = await _tool(client)
    r = await _share(client, t["id"], users=[me.id])
    assert r.status_code == 422 and r.json()["detail"] == "hub_bad_user"
    r = await _share(client, t["id"], users=["00000000-0000-4000-8000-000000000000"])
    assert r.status_code == 422 and r.json()["detail"] == "hub_bad_user"


async def test_share_audited(client, client_factory, db):
    await _as(client, db)
    t = await _tool(client)
    await client.put(f"/api/hub/tools/{t['id']}/secrets", json={"values": {"Authorization": SECRET}})
    friend = await _as(client_factory(), db)
    await _share(client, t["id"], users=[friend.id])
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == "hub.tool_shared"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].data == {"name": "ctx", "teams": [], "users": [str(friend.id)], "everyone": False}
    assert "sk-live" not in str(rows[0].data)
    await _share(client, t["id"], users=[friend.id])  # unchanged: no second row
    assert len((await db.execute(select(AuditLog).where(AuditLog.action == "hub.tool_shared"))).scalars().all()) == 1
