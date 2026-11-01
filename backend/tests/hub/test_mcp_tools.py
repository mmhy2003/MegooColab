from sqlalchemy import select

from app.auth.models import Role
from app.hub.models import HubTool
from tests.factories import login, make_user

SECRET = "Bearer sk-live-abcdef123456"


async def _as(client, db, role=Role.member):
    u = await make_user(db, role=role)
    await login(client, u)
    return u


def _http(name="ctx", secret_value=""):
    return {
        "kind": "mcp",
        "name": name,
        "description": "Reads docs",
        "spec": {
            "transport": "http",
            "url": "https://mcp.example.com/mcp",
            "headers": [{"name": "Authorization", "value": secret_value, "secret": True}],
        },
    }


async def _create(client, body=None):
    r = await client.post("/api/hub/tools", json=body or _http())
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_and_read_mcp(client, db):
    await _as(client, db)
    tool = await _create(client)
    assert tool["secrets"] == [{"name": "Authorization", "set": False}]
    assert tool["secrets_missing"] is True and tool["can_edit"] is True
    r = await client.put(f"/api/hub/tools/{tool['id']}/secrets", json={"values": {"Authorization": SECRET}})
    assert r.status_code == 200 and SECRET not in r.text
    got = await client.get(f"/api/hub/tools/{tool['id']}")
    assert got.status_code == 200
    assert got.json()["secrets"] == [{"name": "Authorization", "set": True}]
    assert got.json()["secrets_missing"] is False
    assert SECRET not in got.text


async def test_secret_value_in_spec_is_ignored(client, db):
    await _as(client, db)
    r = await client.post("/api/hub/tools", json=_http(secret_value="sk-xyz12345678"))
    assert r.status_code == 201
    assert "sk-xyz12345678" not in r.text
    assert r.json()["secrets"] == [{"name": "Authorization", "set": False}]


async def test_duplicate_name_409(client, db):
    await _as(client, db)
    await _create(client)
    r = await client.post("/api/hub/tools", json=_http())
    assert r.status_code == 409 and r.json()["detail"] == "hub_name_taken"


async def test_bad_name_422(client, db):
    await _as(client, db)
    assert (await client.post("/api/hub/tools", json=_http(name="Bad Name"))).status_code == 422


async def test_unknown_placeholder_422(client, db):
    await _as(client, db)
    body = _http()
    body["spec"]["url"] = "https://x/mcp?key=${NOPE}"
    r = await client.post("/api/hub/tools", json=body)
    assert r.status_code == 422 and "hub_unknown_placeholder" in r.text


async def test_other_user_cannot_see_private_tool(client, client_factory, db):
    await _as(client, db)
    tool = await _create(client)
    other = client_factory()
    await _as(other, db)
    assert (await other.get(f"/api/hub/tools/{tool['id']}")).status_code == 404
    assert (await other.delete(f"/api/hub/tools/{tool['id']}")).status_code == 404


async def test_patch_bumps_version_and_rev(client, db):
    await _as(client, db)
    tool = await _create(client)
    tid = tool["id"]
    r = await client.patch(f"/api/hub/tools/{tid}", json={"description": "New words"})
    assert (r.json()["version"], r.json()["rev"]) == (2, 2)
    await client.put(f"/api/hub/tools/{tid}/secrets", json={"values": {"Authorization": SECRET}})
    got = (await client.get(f"/api/hub/tools/{tid}")).json()
    assert (got["version"], got["rev"]) == (2, 3)
    r = await client.patch(f"/api/hub/tools/{tid}", json={"read_only_safe": True})
    assert (r.json()["version"], r.json()["rev"], r.json()["read_only_safe"]) == (2, 4, True)


async def test_removing_slot_drops_value(client, db):
    await _as(client, db)
    tool = await _create(client)
    tid = tool["id"]
    await client.put(f"/api/hub/tools/{tid}/secrets", json={"values": {"Authorization": SECRET}})
    bare = _http()["spec"] | {"headers": []}
    assert (await client.patch(f"/api/hub/tools/{tid}", json={"spec": bare})).json()["secrets"] == []
    r = await client.patch(f"/api/hub/tools/{tid}", json={"spec": _http()["spec"]})
    assert r.json()["secrets"] == [{"name": "Authorization", "set": False}]


async def test_unknown_secret_422(client, db):
    await _as(client, db)
    tool = await _create(client)
    r = await client.put(f"/api/hub/tools/{tool['id']}/secrets", json={"values": {"Nope": "x"}})
    assert r.status_code == 422 and r.json()["detail"] == "hub_unknown_secret"


async def test_clear_secret(client, db):
    await _as(client, db)
    tool = await _create(client)
    await client.put(f"/api/hub/tools/{tool['id']}/secrets", json={"values": {"Authorization": SECRET}})
    r = await client.put(f"/api/hub/tools/{tool['id']}/secrets", json={"values": {"Authorization": ""}})
    assert r.json()["secrets"] == [{"name": "Authorization", "set": False}]


async def test_secrets_encrypted_at_rest(client, db):
    await _as(client, db)
    tool = await _create(client)
    await client.put(f"/api/hub/tools/{tool['id']}/secrets", json={"values": {"Authorization": SECRET}})
    row = (await db.execute(select(HubTool).where(HubTool.name == "ctx"))).scalar_one()
    await db.refresh(row)
    assert row.secrets_enc and SECRET not in row.secrets_enc
    assert all(h["value"] == "" for h in row.spec["headers"])


async def test_delete(client, db):
    await _as(client, db)
    tool = await _create(client)
    assert (await client.delete(f"/api/hub/tools/{tool['id']}")).status_code == 204
    assert (await client.get(f"/api/hub/tools/{tool['id']}")).status_code == 404
