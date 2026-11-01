from app.auth.models import Role
from tests.factories import login, make_team, make_user

SECRET = "Bearer sk-live-abcdef123456"


async def _as(client, db, role=Role.member):
    u = await make_user(db, role=role)
    await login(client, u)
    return u


def _spec(*slots):
    return {
        "transport": "http",
        "url": "https://mcp.example.com/mcp",
        "headers": [{"name": s, "secret": True} for s in slots],
    }


async def _shared_tool(client, client_factory, db, *slots):
    """Owner (client) makes a tool shared with a team that the returned taker client belongs to."""
    owner = await _as(client, db)
    t = (await client.post("/api/hub/tools", json={"kind": "mcp", "name": "ctx", "spec": _spec(*slots)})).json()
    taker = client_factory()
    taker_user = await _as(taker, db)
    team = await make_team(db, owner, taker_user)
    r = await client.put(f"/api/hub/tools/{t['id']}/sharing", json={"teams": [str(team.id)]})
    assert r.status_code == 200, r.text
    return t, taker, team


async def test_copy_has_no_secrets(client, client_factory, db):
    t, taker, _ = await _shared_tool(client, client_factory, db, "API_KEY")
    await client.put(f"/api/hub/tools/{t['id']}/secrets", json={"values": {"API_KEY": SECRET}})
    r = await taker.post(f"/api/hub/tools/{t['id']}/copy")
    assert r.status_code == 201, r.text
    c = r.json()
    assert SECRET not in r.text
    assert c["is_copy"] is True and c["source_state"] == "ok" and c["id"] != t["id"]
    assert c["secrets"] == [{"name": "API_KEY", "set": False}] and c["secrets_missing"] is True
    assert c["source"]["id"] == t["id"] and c["source"]["version"] == 1
    assert c["read_only_safe"] is False and c["sharing"] == {"teams": [], "users": [], "everyone": False}
    assert [x["name"] for x in (await taker.get("/api/hub/tools", params={"shelf": "mine"})).json()] == ["ctx"]


async def test_copy_own_tool_or_twice_409(client, client_factory, db):
    t, taker, _ = await _shared_tool(client, client_factory, db, "API_KEY")
    assert (await client.post(f"/api/hub/tools/{t['id']}/copy")).status_code == 409
    assert (await taker.post(f"/api/hub/tools/{t['id']}/copy")).status_code == 201
    r = await taker.post(f"/api/hub/tools/{t['id']}/copy")
    assert r.status_code == 409 and r.json()["detail"] == "hub_already_copied"


async def test_copy_name_clash_409(client, client_factory, db):
    t, taker, _ = await _shared_tool(client, client_factory, db)
    await taker.post("/api/hub/tools", json={"kind": "mcp", "name": "ctx", "spec": _spec()})
    r = await taker.post(f"/api/hub/tools/{t['id']}/copy")
    assert r.status_code == 409 and r.json()["detail"] == "hub_name_taken"


async def test_copy_invisible_404(client, client_factory, db):
    await _as(client, db)
    t = (await client.post("/api/hub/tools", json={"kind": "mcp", "name": "ctx", "spec": _spec()})).json()
    other = client_factory()
    await _as(other, db)
    assert (await other.post(f"/api/hub/tools/{t['id']}/copy")).status_code == 404


async def test_update_available_then_take(client, client_factory, db):
    t, taker, _ = await _shared_tool(client, client_factory, db, "API_KEY")
    c = (await taker.post(f"/api/hub/tools/{t['id']}/copy")).json()
    r = await taker.post(f"/api/hub/tools/{c['id']}/update")
    assert r.status_code == 409 and r.json()["detail"] == "hub_no_update"
    await client.patch(f"/api/hub/tools/{t['id']}", json={"description": "Better words"})
    assert (await taker.get(f"/api/hub/tools/{c['id']}")).json()["source_state"] == "update_available"
    summaries = (await taker.get("/api/hub/tools", params={"shelf": "mine"})).json()
    assert summaries[0]["source_state"] == "update_available"
    r = await taker.post(f"/api/hub/tools/{c['id']}/update")
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["source_state"], got["version"], got["description"]) == ("ok", 2, "Better words")
    assert got["rev"] > c["rev"]


async def test_update_keeps_secrets_for_surviving_slots(client, client_factory, db):
    t, taker, _ = await _shared_tool(client, client_factory, db, "API_KEY")
    c = (await taker.post(f"/api/hub/tools/{t['id']}/copy")).json()
    await taker.put(f"/api/hub/tools/{c['id']}/secrets", json={"values": {"API_KEY": "mine-1234"}})
    await client.patch(f"/api/hub/tools/{t['id']}", json={"spec": _spec("API_KEY", "TOKEN")})
    got = (await taker.post(f"/api/hub/tools/{c['id']}/update")).json()
    assert got["secrets"] == [{"name": "API_KEY", "set": True}, {"name": "TOKEN", "set": False}]
    assert got["secrets_missing"] is True


async def test_unshared_source_shows_no_longer_shared(client, client_factory, db):
    t, taker, _ = await _shared_tool(client, client_factory, db)
    c = (await taker.post(f"/api/hub/tools/{t['id']}/copy")).json()
    await client.put(f"/api/hub/tools/{t['id']}/sharing", json={})
    got = (await taker.get(f"/api/hub/tools/{c['id']}")).json()
    assert got["source_state"] == "no_longer_shared" and got["source"] is None
    assert (await taker.post(f"/api/hub/tools/{c['id']}/update")).status_code == 409


async def test_deleted_source_shows_no_longer_shared(client, client_factory, db):
    t, taker, _ = await _shared_tool(client, client_factory, db)
    c = (await taker.post(f"/api/hub/tools/{t['id']}/copy")).json()
    await client.delete(f"/api/hub/tools/{t['id']}")
    got = (await taker.get(f"/api/hub/tools/{c['id']}")).json()
    assert got["is_copy"] is True and got["source_state"] == "no_longer_shared"


async def test_copy_of_skill_copies_files(client, client_factory, db):
    import io
    import zipfile

    owner = await _as(client, db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", "---\nname: ui-review\ndescription: d\n---\n")
        z.writestr("a.sh", "echo")
    t = (await client.post("/api/hub/skills", files={"file": ("s.zip", buf.getvalue(), "application/zip")})).json()
    taker = client_factory()
    taker_user = await _as(taker, db)
    team = await make_team(db, owner, taker_user)
    await client.put(f"/api/hub/tools/{t['id']}/sharing", json={"teams": [str(team.id)]})
    c = (await taker.post(f"/api/hub/tools/{t['id']}/copy")).json()
    assert [f["path"] for f in c["files"]] == ["SKILL.md", "a.sh"] and c["runs_code"] is True
    r = await taker.get(f"/api/hub/tools/{c['id']}/file", params={"path": "a.sh"})
    assert r.json()["text"] == "echo"


async def test_copy_edits_refused_until_owned(client, client_factory, db):
    t, taker, _ = await _shared_tool(client, client_factory, db)
    c = (await taker.post(f"/api/hub/tools/{t['id']}/copy")).json()
    r = await taker.patch(f"/api/hub/tools/{c['id']}", json={"description": "mine now"})
    assert r.status_code == 409 and r.json()["detail"] == "hub_copy_read_only"
    assert (await taker.patch(f"/api/hub/tools/{c['id']}", json={"read_only_safe": True})).status_code == 200
    r = await taker.put(f"/api/hub/tools/{c['id']}/sharing", json={"everyone": True})
    assert r.status_code == 409 and r.json()["detail"] == "hub_copy_read_only"
    owned = (await taker.post(f"/api/hub/tools/{c['id']}/own")).json()
    assert owned["is_copy"] is False and owned["source_state"] is None and owned["can_edit"] is True
    r = await taker.patch(f"/api/hub/tools/{c['id']}", json={"description": "mine now"})
    assert r.status_code == 200 and r.json()["description"] == "mine now"
    r = await taker.post(f"/api/hub/tools/{t['id']}/copy")  # no live copy any more, but the name is taken
    assert r.status_code == 409 and r.json()["detail"] == "hub_name_taken"
