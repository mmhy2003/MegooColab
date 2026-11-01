"""Plan 23 final review: fixes, each with the test that showed the problem."""

import io
import zipfile

from sqlalchemy import event

from app.auth.models import Role
from app.core.db import engine
from tests.factories import login, make_user

SKILL_MD = b"---\nname: ui-review\ndescription: d\n---\n"


async def _as(client, db, role=Role.member):
    u = await make_user(db, role=role)
    await login(client, u)
    return u


def _stdio(args, acknowledged=()):
    return {"transport": "stdio", "command": {"command": "npx", "args": list(args)}, "acknowledged": list(acknowledged)}


async def test_shared_tool_cannot_be_edited_to_hold_a_key(client, db):
    await _as(client, db)
    t = (await client.post("/api/hub/tools", json={"kind": "mcp", "name": "ctx", "spec": _stdio(["pkg"])})).json()
    assert (await client.put(f"/api/hub/tools/{t['id']}/sharing", json={"everyone": True})).status_code == 200
    r = await client.patch(f"/api/hub/tools/{t['id']}", json={"spec": _stdio(["pkg", "--api-key", "sk-live1234567890"])})
    assert r.status_code == 409 and r.json()["detail"] == "hub_flagged_values"
    assert "sk-live1234567890" not in (await client.get(f"/api/hub/tools/{t['id']}")).text
    # a private tool may hold one (it is flagged, and sharing waits until it is dealt with)
    await client.put(f"/api/hub/tools/{t['id']}/sharing", json={})
    r = await client.patch(f"/api/hub/tools/{t['id']}", json={"spec": _stdio(["pkg", "--api-key", "sk-live1234567890"])})
    assert r.status_code == 200 and r.json()["flagged"] == ["args[2]"]


async def test_acknowledgement_lapses_when_the_value_changes(client, db):
    await _as(client, db)
    uuid_arg = "0f6c1b2a3d4e5f60718293a4b5c6d7e8"
    spec = _stdio(["pkg", uuid_arg], acknowledged=["args[1]"])
    t = (await client.post("/api/hub/tools", json={"kind": "mcp", "name": "ctx", "spec": spec})).json()
    assert t["flagged"] == []
    r = await client.patch(
        f"/api/hub/tools/{t['id']}", json={"spec": _stdio(["pkg", "sk-live1234567890"], acknowledged=["args[1]"])}
    )
    assert r.status_code == 200 and r.json()["flagged"] == ["args[1]"]
    assert r.json()["spec"]["acknowledged"] == []


async def test_finder_zip_with_macosx_entries(client, db):
    await _as(client, db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ui-review/SKILL.md", SKILL_MD)
        z.writestr("ui-review/.DS_Store", b"\0")
        z.writestr("__MACOSX/ui-review/._SKILL.md", b"\0")
        z.writestr("ui-review/._notes.md", b"\0")
    r = await client.post("/api/hub/skills", files={"file": ("s.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 201, r.text
    assert [f["path"] for f in r.json()["files"]] == ["SKILL.md"]


async def test_shelf_list_does_not_read_file_contents(client, db):
    await _as(client, db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", SKILL_MD)
        z.writestr("big.sh", b"x" * 100_000)
    assert (await client.post("/api/hub/skills", files={"file": ("s.zip", buf.getvalue(), "application/zip")})).status_code == 201
    seen: list[str] = []

    def _capture(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _capture)
    try:
        rows = (await client.get("/api/hub/tools", params={"shelf": "mine"})).json()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)
    assert rows[0]["runs_code"] is True
    assert not [s for s in seen if "hub_tool_files.content" in s]
