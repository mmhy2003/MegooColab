"""Tool Hub import (plan 24): what a machine's runner finds set up by hand, brought into the library on request."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.hub.models import HubScan, HubTool
from app.runner.router import _handle
from tests.hub.test_machines import _machine, _me, conns  # noqa: F401 - the fixture

GHP = "ghp_abcdefghijklmnopqrstu1234"


def _found(scan_id, items):
    return json.dumps({"type": "tools_found", "scan_id": scan_id, "items": items})


def _stdio(program, env_value=GHP):
    return {"program": program, "kind": "mcp", "name": "gh",
            "mcp": {"transport": "stdio", "command": "npx", "args": ["-y", "gh-mcp"], "headers": {},
                    "env": {"GITHUB_TOKEN": env_value, "LOG_LEVEL": "info"}}}


async def _scan(client, db, conns, items):  # noqa: F811
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    r = await client.post(f"/api/hub/machines/{token}/scan")
    assert r.status_code == 202, r.text
    scan_id = r.json()["scan_id"]
    assert conn.socket.sent[-1] == {"type": "tools_scan", "scan_id": scan_id}
    waiting = (await client.get(f"/api/hub/scans/{scan_id}")).json()
    assert waiting == {"status": "waiting", "items": []}
    assert await _handle(conn, _found(scan_id, items))
    return scan_id


async def test_found_items_merge_and_mask(client, db, conns):  # noqa: F811
    skill = {"program": "codex", "kind": "skill", "name": "notes",
             "files": [{"path": "SKILL.md", "content_b64": base64.b64encode(b"---\nname: notes\n---\n").decode()}]}
    odd = {"program": "claude_code", "kind": "mcp", "name": "old", "problem": "not supported: sse"}
    scan_id = await _scan(client, db, conns, [_stdio("claude_code"), _stdio("codex"), skill, odd])
    r = await client.get(f"/api/hub/scans/{scan_id}")
    assert r.status_code == 200 and GHP not in r.text
    body = r.json()
    assert body["status"] == "done"
    by_name = {i["name"]: i for i in body["items"]}
    gh = by_name["gh"]
    assert gh["programs"] == ["claude_code", "codex"] and gh["exists_in_library"] is False
    env = {e["name"]: e for e in gh["mcp"]["env"]}
    assert env["GITHUB_TOKEN"] == {"name": "GITHUB_TOKEN", "value_masked": "••••1234", "suggested_secret": True}
    assert env["LOG_LEVEL"] == {"name": "LOG_LEVEL", "value_masked": "info", "suggested_secret": False}
    assert gh["mcp"]["command"] == "npx" and gh["mcp"]["args"] == ["-y", "gh-mcp"]
    assert by_name["notes"]["files"] == [{"path": "SKILL.md", "size": 20, "runs_on": None}]
    assert by_name["old"]["problem"] == "not supported: sse"


async def test_different_setups_stay_apart(client, db, conns):  # noqa: F811
    scan_id = await _scan(client, db, conns, [_stdio("claude_code"), _stdio("codex", env_value="other-value")])
    items = (await client.get(f"/api/hub/scans/{scan_id}")).json()["items"]
    assert sorted(i["programs"][0] for i in items) == ["claude_code", "codex"]


async def test_accept_stores_secret_encrypted(client, db, conns):  # noqa: F811
    scan_id = await _scan(client, db, conns, [_stdio("claude_code")])
    item = (await client.get(f"/api/hub/scans/{scan_id}")).json()["items"][0]
    r = await client.post(f"/api/hub/scans/{scan_id}/accept", json={"items": [
        {"index": item["index"], "name": "github", "secret": ["GITHUB_TOKEN"], "description": "From my laptop"}]})
    assert r.status_code == 200, r.text
    assert GHP not in r.text
    [tool] = r.json()
    assert tool["name"] == "github" and tool["description"] == "From my laptop"
    assert tool["secrets"] == [{"name": "GITHUB_TOKEN", "set": True}]
    assert {e["name"]: e["value"] for e in tool["spec"]["env"]} == {"GITHUB_TOKEN": "", "LOG_LEVEL": "info"}
    row = (await db.execute(select(HubTool).where(HubTool.name == "github"))).scalar_one()
    assert GHP not in (row.secrets_enc or "") and GHP not in json.dumps(row.spec)
    assert (await client.get(f"/api/hub/scans/{scan_id}")).status_code == 404  # used up


async def test_accept_skill_with_files(client, db, conns):  # noqa: F811
    skill = {"program": "claude_code", "kind": "skill", "name": "notes",
             "files": [{"path": "SKILL.md", "content_b64": base64.b64encode(b"---\nname: notes\ndescription: d\n---\n").decode()},
                       {"path": "run.sh", "content_b64": base64.b64encode(b"echo").decode()}]}
    scan_id = await _scan(client, db, conns, [skill])
    r = await client.post(f"/api/hub/scans/{scan_id}/accept", json={"items": [
        {"index": 0, "name": "notes", "secret": [], "description": ""}]})
    [tool] = r.json()
    assert tool["kind"] == "skill" and [f["path"] for f in tool["files"]] == ["SKILL.md", "run.sh"] and tool["runs_code"]


async def test_exists_in_library_and_name_clash(client, db, conns):  # noqa: F811
    scan_id = await _scan(client, db, conns, [_stdio("claude_code")])
    await client.post("/api/hub/tools", json={"kind": "mcp", "name": "gh", "spec": {
        "transport": "http", "url": "https://x/mcp"}})
    item = (await client.get(f"/api/hub/scans/{scan_id}")).json()["items"][0]
    assert item["exists_in_library"] is True
    r = await client.post(f"/api/hub/scans/{scan_id}/accept", json={"items": [
        {"index": 0, "name": "gh", "secret": ["GITHUB_TOKEN"], "description": ""}]})
    assert r.status_code == 409 and r.json()["detail"] == "hub_name_taken"


async def test_scan_expires(client, db, conns):  # noqa: F811
    scan_id = await _scan(client, db, conns, [_stdio("claude_code")])
    await db.execute(update(HubScan).where(HubScan.id == uuid.UUID(scan_id)).values(
        created_at=datetime.now(UTC) - timedelta(hours=2)))
    await db.commit()
    r = await client.get(f"/api/hub/scans/{scan_id}")
    assert r.status_code == 410 and r.json()["detail"] == "hub_scan_expired"


async def test_other_users_scan_404(client, client_factory, db, conns):  # noqa: F811
    scan_id = await _scan(client, db, conns, [_stdio("claude_code")])
    other = client_factory()
    await _me(other, db)
    assert (await other.get(f"/api/hub/scans/{scan_id}")).status_code == 404
    assert (await other.post(f"/api/hub/scans/{scan_id}/accept", json={"items": []})).status_code == 404


async def test_scan_needs_an_online_runner(client, db, conns):  # noqa: F811
    me = await _me(client, db)
    token = await _machine(client, db)
    r = await client.post(f"/api/hub/machines/{token}/scan")
    assert r.status_code == 409 and r.json()["detail"] == "hub_runner_offline"
    conns(token, me, capabilities=("workflow/1",))
    r = await client.post(f"/api/hub/machines/{token}/scan")
    assert r.status_code == 409 and r.json()["detail"] == "hub_runner_too_old"


async def test_found_for_another_machine_is_ignored(client, db, conns):  # noqa: F811
    scan_id = await _scan(client, db, conns, [])
    stranger = await _me(client, db)
    other_token = await _machine(client, db, name="other")
    conn = conns(other_token, stranger)
    assert await _handle(conn, _found(scan_id, [_stdio("claude_code")]))
    rows = (await db.execute(select(HubScan))).scalars().all()
    assert len(rows) == 1
