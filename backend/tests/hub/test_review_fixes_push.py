"""Plan 24 final review: each test pins a finding."""

import json

from app.runner.protocol import runner_message
from app.runner.router import _handle
from tests.hub.test_import import _scan
from tests.hub.test_machines import (  # noqa: F401
    _machine,
    _machines,
    _me,
    _push,
    _report,
    _state,
    _tool,
    conns,
)


async def test_push_stays_pending_until_the_runner_reports(client, db, conns):  # noqa: F811
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": "k"})
    m = (await _push(client, token, [t["id"]])).json()
    assert m["pending"] is True and _state(m, "ctx") == "will_install"  # online: not "waiting"
    await _report(conn, conn.socket.pushes()[0])
    assert (await _machines(client))[0]["pending"] is False


async def test_push_too_large_is_refused(client, db, conns, monkeypatch):  # noqa: F811
    from app.hub import machines

    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": "k"})
    monkeypatch.setattr(machines, "MAX_PUSH_BYTES", 100)
    r = await _push(client, token, [t["id"]])
    assert r.status_code == 409 and r.json()["detail"] == "hub_push_too_large"
    assert conn.socket.pushes() == []


async def test_a_tool_that_loses_its_key_stays_installed(client, db, conns):  # noqa: F811
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": "k"})
    other = await _tool(client, "other", secrets={"API_KEY": "k"})
    await _push(client, token, [t["id"]])
    await _report(conn, conn.socket.pushes()[0])
    spec = {"transport": "http", "url": "https://mcp.example.com/mcp?key=${API_KEY}",
            "headers": [{"name": "API_KEY", "secret": True}, {"name": "NEW", "secret": True}]}
    await client.patch(f"/api/hub/tools/{t['id']}", json={"spec": spec})
    m = (await _push(client, token, [t["id"], other["id"]])).json()
    assert _state(m, "ctx") == "key_missing" and next(x for x in m["tools"] if x["name"] == "ctx")["ticked"] is True
    push = conn.socket.pushes()[-1]
    assert [x["name"] for x in push["tools"]] == ["other"] and push["keep"] == ["ctx"]


async def test_a_key_missing_tool_can_be_ticked(client, db, conns):  # noqa: F811
    me = await _me(client, db)
    token = await _machine(client, db)
    conns(token, me)
    t = await _tool(client)
    r = await _push(client, token, [t["id"]])
    assert r.status_code == 200 and _state(r.json(), "ctx") == "key_missing"


async def test_a_failed_removal_shows(client, db, conns):  # noqa: F811
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": "k"})
    await _push(client, token, [t["id"]])
    await _report(conn, conn.socket.pushes()[0])
    await _push(client, token, [])
    await _handle(conn, json.dumps({"type": "tools_report", "push_id": conn.socket.pushes()[-1]["push_id"], "results": [
        {"tool_id": t["id"], "name": "ctx", "kind": "mcp", "program": "claude_code", "status": "failed",
         "detail": "config.toml could not be read"}]}))
    m = (await _machines(client))[0]
    assert _state(m, "ctx") == "failed" and m["out_of_step"] is True


async def test_a_failed_removal_of_a_deleted_tool_shows_and_clears(client, db, conns):  # noqa: F811
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": "k"})
    await _push(client, token, [t["id"]])
    await _report(conn, conn.socket.pushes()[0])
    await client.delete(f"/api/hub/tools/{t['id']}")
    await _push(client, token, [])
    await _handle(conn, json.dumps({"type": "tools_report", "push_id": conn.socket.pushes()[-1]["push_id"], "results": [
        {"name": "ctx", "kind": "mcp", "program": "claude_code", "status": "failed", "detail": "x"}]}))
    assert _state((await _machines(client))[0], "ctx") == "failed"
    await _push(client, token, [])  # tried again: the old failure is forgotten until the runner reports
    assert (await _machines(client))[0]["tools"] == []


async def test_scan_masks_a_url_holding_a_key(client, db, conns):  # noqa: F811
    item = {"program": "claude_code", "kind": "mcp", "name": "web",
            "mcp": {"transport": "http", "url": "https://mcp.example.com/mcp?api_key=sk-live-abcdefgh1234", "headers": {},
                    "args": [], "env": {}}}
    scan_id = await _scan(client, db, conns, [item])
    r = await client.get(f"/api/hub/scans/{scan_id}")
    assert "sk-live-abcdefgh1234" not in r.text
    assert r.json()["items"][0]["mcp"]["url"] == "https://mcp.example.com/••••"


def test_found_mcp_with_many_args_is_accepted():
    found = {"type": "tools_found", "scan_id": "s", "items": [{"program": "codex", "kind": "mcp", "name": "x",
             "mcp": {"transport": "stdio", "command": "c", "args": [str(i) for i in range(300)], "headers": {},
                     "env": {f"K{i}": "v" for i in range(300)}}}]}
    assert runner_message.validate_python(found).items[0].mcp.args[-1] == "299"
