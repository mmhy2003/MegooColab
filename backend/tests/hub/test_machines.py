"""Tool Hub, part 2 (plan 24): a person's machines, what is ticked on each, pushes and what the runner reports."""

import json
import uuid

import pytest
from sqlalchemy import update

from app.auth.models import PersonalAccessToken
from app.runner.registry import RunnerConn, registry
from app.runner.router import _handle
from tests.factories import login, make_user

SECRET = "Bearer sk-live-abcdef123456"


class _Socket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self, code=1000):
        pass

    def pushes(self):
        return [m for m in self.sent if m["type"] == "tools_push"]


@pytest.fixture
def conns():
    made: list[uuid.UUID] = []

    def _online(token_id, user, capabilities=("tools/1",)):
        conn = RunnerConn(uuid.UUID(token_id), user.id, _Socket())
        conn.capabilities = set(capabilities)
        registry._conns[conn.token_id] = conn
        made.append(conn.token_id)
        return conn

    yield _online
    for t in made:
        registry._conns.pop(t, None)


async def _me(client, db):
    u = await make_user(db)
    await login(client, u)
    return u


async def _machine(client, db, os_="linux", program="claude_code", name="laptop"):
    r = await client.post("/api/tokens", json={"name": name, "scopes": ["runner"]})
    assert r.status_code == 201, r.text
    token_id = r.json()["token"]["id"]
    await db.execute(update(PersonalAccessToken).where(PersonalAccessToken.id == uuid.UUID(token_id)).values(runner_os=os_))
    await db.commit()
    a = await client.post("/api/agents", json={"program": program, "runner_token_id": token_id, "name": f"{name}-{program}"})
    assert a.status_code == 201, a.text
    return token_id


async def _tool(client, name="ctx", spec=None, secrets=None):
    spec = spec or {
        "transport": "http",
        "url": "https://mcp.example.com/mcp?key=${API_KEY}",
        "headers": [{"name": "API_KEY", "secret": True}, {"name": "X-Team", "value": "web"}],
    }
    t = (await client.post("/api/hub/tools", json={"kind": "mcp", "name": name, "spec": spec})).json()
    if secrets is not None:
        await client.put(f"/api/hub/tools/{t['id']}/secrets", json={"values": secrets})
    return t


async def _push(client, token_id, tool_ids, take_over=()):
    return await client.post(f"/api/hub/machines/{token_id}/push",
                             json={"tool_ids": list(tool_ids), "take_over": list(take_over)})


def _state(machine, tool_name, program="claude_code"):
    tool = next(t for t in machine["tools"] if t["name"] == tool_name)
    return next(p["state"] for p in tool["programs"] if p["program"] == program)


async def _machines(client):
    r = await client.get("/api/hub/machines")
    assert r.status_code == 200, r.text
    return r.json()


async def _report(conn, push, status="installed", program="claude_code", **extra):
    results = [{"tool_id": t["tool_id"], "name": t["name"], "kind": t["kind"], "program": program, "rev": t["rev"],
                "status": status, "detail": ""} | extra for t in push["tools"]]
    assert await _handle(conn, json.dumps({"type": "tools_report", "push_id": push["push_id"], "results": results}))


async def test_push_delivers_resolved_secrets(client, db, conns):
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": SECRET})
    r = await _push(client, token, [t["id"]])
    assert r.status_code == 200, r.text
    assert SECRET not in r.text
    [push] = conn.socket.pushes()
    assert push["programs"] == ["claude_code"] and push["take_over"] == []
    [payload] = push["tools"]
    assert payload["name"] == "ctx" and payload["rev"] == t["rev"] + 1  # the secret save bumped rev
    assert payload["mcp"]["url"] == f"https://mcp.example.com/mcp?key={SECRET}"
    assert payload["mcp"]["headers"] == {"API_KEY": SECRET, "X-Team": "web"}
    assert _state(r.json(), "ctx") == "will_install"


async def test_push_offline_waits_then_delivers_current_state(client, db, conns):
    me = await _me(client, db)
    token = await _machine(client, db)
    t = await _tool(client, secrets={"API_KEY": "k1"})
    r = await _push(client, token, [t["id"]])
    m = r.json()
    assert m["pending"] is True and m["online"] is False and _state(m, "ctx") == "waiting"
    await client.patch(f"/api/hub/tools/{t['id']}", json={"description": "newer"})
    rev = (await client.get(f"/api/hub/tools/{t['id']}")).json()["rev"]
    conn = conns(token, me)
    hello = {"type": "hello", "runner_version": "1", "os": "linux", "arch": "amd64", "agents": [],
             "capabilities": ["tools/1"]}
    assert await _handle(conn, json.dumps(hello))
    [push] = conn.socket.pushes()
    assert push["tools"][0]["rev"] == rev
    m = (await _machines(client))[0]
    assert m["pending"] is True and _state(m, "ctx") == "will_install"  # delivered, not yet reported
    await _report(conn, push)
    m = (await _machines(client))[0]
    assert m["pending"] is False and _state(m, "ctx") == "installed"


async def test_report_marks_installed_then_update_ready_after_edit(client, db, conns):
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": "k"})
    await _push(client, token, [t["id"]])
    await _report(conn, conn.socket.pushes()[0])
    m = (await _machines(client))[0]
    assert _state(m, "ctx") == "installed" and m["out_of_step"] is False
    assert (await client.get("/api/hub/machines/summary")).json() == {"out_of_step": False}
    await client.put(f"/api/hub/tools/{t['id']}/secrets", json={"values": {"API_KEY": "rotated"}})
    m = (await _machines(client))[0]
    assert _state(m, "ctx") == "update_ready" and m["out_of_step"] is True
    assert (await client.get("/api/hub/machines/summary")).json() == {"out_of_step": True}


async def test_deleted_tool_will_remove(client, db, conns):
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": "k"})
    await _push(client, token, [t["id"]])
    await _report(conn, conn.socket.pushes()[0])
    await client.delete(f"/api/hub/tools/{t['id']}")
    m = (await _machines(client))[0]
    assert _state(m, "ctx") == "will_remove"
    await _push(client, token, [])
    assert conn.socket.pushes()[-1]["tools"] == []
    await _handle(conn, json.dumps({"type": "tools_report", "push_id": conn.socket.pushes()[-1]["push_id"], "results": [
        {"name": "ctx", "kind": "mcp", "program": "claude_code", "status": "removed", "detail": ""}]}))
    assert (await _machines(client))[0]["tools"] == []


async def test_conflict_then_take_over(client, db, conns):
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": "k"})
    await _push(client, token, [t["id"]])
    await _report(conn, conn.socket.pushes()[0], status="conflict")
    assert _state((await _machines(client))[0], "ctx") == "conflict"
    await _push(client, token, [t["id"]], take_over=[t["id"]])
    assert conn.socket.pushes()[-1]["take_over"] == ["ctx"]


async def test_programs_from_linked_agents(client, db, conns):
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": "k"})
    await _push(client, token, [t["id"]])
    await _report(conn, conn.socket.pushes()[0])
    await client.post("/api/agents", json={"program": "codex", "runner_token_id": token})
    m = (await _machines(client))[0]
    assert [a["program"] for a in m["agents"]] == ["claude_code", "codex"]
    assert _state(m, "ctx", "claude_code") == "installed" and _state(m, "ctx", "codex") == "will_install"


async def test_drift_changed(client, db, conns):
    me = await _me(client, db)
    token = await _machine(client, db)
    conn = conns(token, me)
    t = await _tool(client, secrets={"API_KEY": "k"})
    await _push(client, token, [t["id"]])
    await _report(conn, conn.socket.pushes()[0])
    drift = {"type": "tools_drift", "items": [{"name": "ctx", "kind": "mcp", "program": "claude_code", "status": "missing"}]}
    assert await _handle(conn, json.dumps(drift))
    assert _state((await _machines(client))[0], "ctx") == "changed"
    assert await _handle(conn, json.dumps({"type": "tools_drift", "items": []}))
    assert _state((await _machines(client))[0], "ctx") == "installed"


async def test_not_your_machine_404(client, client_factory, db):
    await _me(client, db)
    token = await _machine(client, db)
    other = client_factory()
    await _me(other, db)
    assert (await _push(other, token, [])).status_code == 404
    assert (await _machines(other)) == []


async def test_runner_too_old(client, db, conns):
    me = await _me(client, db)
    token = await _machine(client, db)
    conns(token, me, capabilities=("workflow/1",))
    t = await _tool(client, secrets={"API_KEY": "k"})
    m = (await _machines(client))[0]
    assert m["online"] is True and m["supports_tools"] is False
    r = await _push(client, token, [t["id"]])
    assert r.status_code == 409 and r.json()["detail"] == "hub_runner_too_old"


async def test_default_set_on_new_machine(client, db, conns):
    await _me(client, db)
    t = await _tool(client, secrets={"API_KEY": "k"})
    await _tool(client, "nokey")  # in the default set but its key is missing: left out
    await client.patch(f"/api/hub/tools/{t['id']}", json={"in_default_set": True})
    nokey = next(x for x in (await client.get("/api/hub/tools")).json() if x["name"] == "nokey")
    await client.patch(f"/api/hub/tools/{nokey['id']}", json={"in_default_set": True})
    assert (await client.put("/api/hub/prefs", json={"auto_default": True})).json() == {"auto_default": True}
    token = await _machine(client, db)
    m = (await _machines(client))[0]
    ticked = {x["name"] for x in m["tools"] if x["ticked"]}
    assert ticked == {"ctx"} and m["pending"] is True
    # a second agent on that machine: not a new machine, nothing changes
    await client.post("/api/hub/machines/" + token + "/push", json={"tool_ids": [], "take_over": []})
    await client.post("/api/agents", json={"program": "codex", "runner_token_id": token})
    assert not any(x["ticked"] for x in (await _machines(client))[0]["tools"])


async def test_windows_os_command(client, db, conns):
    me = await _me(client, db)
    win = await _machine(client, db, os_="windows", name="win")
    lin = await _machine(client, db, os_="linux", name="lin")
    spec = {"transport": "stdio", "os_commands": {"windows": {"command": "x.exe", "args": ["--q"]}}}
    t = await _tool(client, "x", spec=spec)
    cw, cl = conns(win, me), conns(lin, me)
    await _push(client, win, [t["id"]])
    assert cw.socket.pushes()[0]["tools"][0]["mcp"]["command"] == "x.exe"
    r = await _push(client, lin, [t["id"]])
    assert cl.socket.pushes()[0]["tools"] == []
    assert _state(r.json(), "x") == "not_available"


async def test_machine_reports_runner_version(client, db, conns):
    user = await _me(client, db)
    token_id = await _machine(client, db)
    assert (await _machines(client))[0]["runner_version"] is None
    conns(token_id, user).version = "0.5.0"
    assert (await _machines(client))[0]["runner_version"] == "0.5.0"
