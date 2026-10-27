"""MCP server tests: the SDK's Streamable HTTP client talking to the ASGI app in-process."""

import contextlib
import json

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

from app.auth.models import Role
from app.tasks.models import Task, TaskEvent
from tests.factories import login, make_project, make_user

URL = "http://test/api/mcp"


async def _mint(client, scopes=("mcp",)) -> str:
    r = await client.post("/api/tokens", json={"name": "t", "scopes": list(scopes)})
    assert r.status_code == 201, r.text
    return r.json()["secret"]


@contextlib.asynccontextmanager
async def mcp_session(app, secret: str):
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        headers={"Authorization": f"Bearer {secret}"},
    )
    async with (
        http,
        streamable_http_client(URL, http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


async def call(session, name: str, **args):
    """(is_error, payload) where payload is the parsed JSON, or the error text."""
    res = await session.call_tool(name, args)
    text = res.content[0].text if res.content else ""
    if res.is_error:
        return True, text
    return False, (res.structured_content.get("result", res.structured_content) if res.structured_content else json.loads(text))


async def test_mcp_requires_bearer_401(client, mcp_running):
    for headers in ({}, {"Authorization": "Bearer mgc_nope"}):
        r = await client.post(
            "/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={**headers, "Accept": "application/json, text/event-stream"},
        )
        assert r.status_code == 401
        assert r.json() == {"detail": "invalid_token"}


async def test_mcp_without_any_headers_is_401_not_csrf(client_factory, db, mcp_running):
    """No token, no client header: the CSRF guard must not answer first (MCP never accepts cookies)."""
    bare = client_factory()
    del bare.headers["X-Megoo-Client"]
    r = await bare.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid_token"}
    assert r.headers["www-authenticate"] == "Bearer"
    # a browser session cookie is not a credential here either
    user = await make_user(db)
    bare.headers["X-Megoo-Client"] = "web"
    await login(bare, user)
    del bare.headers["X-Megoo-Client"]
    r = await bare.post(
        "/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


async def test_mcp_rejects_runner_only_token_401(client, db, mcp_running):
    user = await make_user(db)
    await login(client, user)
    secret = await _mint(client, scopes=("runner",))
    r = await client.post(
        "/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": f"Bearer {secret}", "Accept": "application/json, text/event-stream"},
    )
    assert r.status_code == 401


async def test_tools_list_contains_expected_names(app, client, db, mcp_running):
    user = await make_user(db)
    await login(client, user)
    async with mcp_session(app, await _mint(client)) as s:
        names = {t.name for t in (await s.list_tools()).tools}
    assert names == {
        "whoami", "list_projects", "list_tasks", "get_task", "create_task",
        "update_task", "move_task", "comment_on_task",
        "get_workflow", "get_document", "ask_human", "submit_design", "submit_plan", "complete_step",
        "submit_review", "report_finish", "show_mockup",
        "kb_search", "kb_list", "kb_read", "kb_write",
        "search_memory", "ask_memory",
        "find_answer", "ask_project", "get_question", "withdraw_question", "submit_answer",
    }
    # the endpoint works without a trailing slash and other API routes are unaffected
    assert (await client.get("/api/health")).status_code == 200


async def test_whoami(app, client, db, mcp_running):
    user = await make_user(db, name="Ada")
    await login(client, user)
    async with mcp_session(app, await _mint(client)) as s:
        err, me = await call(s, "whoami")
    assert not err
    assert me["email"] == user.email and me["name"] == "Ada" and me["role"] == "member"


async def test_list_and_get_tasks_respect_project_access(app, client, client_factory, db, mcp_running):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    mgr_secret = await _mint(client)
    outsider = await make_user(db)
    other = client_factory()
    await login(other, outsider)
    out_secret = await _mint(other)

    async with mcp_session(app, mgr_secret) as s:
        err, created = await call(s, "create_task", project_key="PAY", title="First", description_md="d")
        assert not err and created["key"] == "PAY-1"
        err, projects = await call(s, "list_projects")
        assert [p["key"] for p in projects] == ["PAY"]
        err, tasks = await call(s, "list_tasks", project_key="PAY")
        assert [t["key"] for t in tasks] == ["PAY-1"] and tasks[0]["title"] == "First"
        err, task = await call(s, "get_task", key="PAY-1")
        assert not err and task["title"] == "First"
        assert [a["kind"] for a in task["activity"]] == ["created"]
        err, mine = await call(s, "list_tasks", project_key="PAY", mine=True)
        assert mine == []

    async with mcp_session(app, out_secret) as s:
        err, text = await call(s, "list_tasks", project_key="PAY")
        assert err and "project_not_found" in text
        err, text = await call(s, "get_task", key="PAY-1")
        assert err and "project_not_found" in text
        err, projects = await call(s, "list_projects")
        assert projects == []


async def test_create_and_move_task_via_mcp_publishes_events(app, client, db, mcp_running):
    _project, manager, _ = await make_project(client, db, "PAY")
    secret = await _mint(client)
    cols = {c["name"].lower(): c for c in (await client.get("/api/projects/PAY/columns")).json()}
    done = next(c for c in cols.values() if c["category"] == "done")


    async with mcp_session(app, secret) as s:
        err, _ = await call(s, "create_task", project_key="PAY", title="Ship it")
        assert not err
        err, moved = await call(s, "move_task", key="PAY-1", column=done["name"].upper())
        assert not err and moved["column_id"] == done["id"] and moved["completed_at"]
        err, text = await call(s, "move_task", key="PAY-1", column="nope")
        assert err and "invalid_column" in text
        err, upd = await call(s, "update_task", key="PAY-1", title="Ship it now", story_points=3)
        assert not err and upd["title"] == "Ship it now" and upd["story_points"] == 3
        err, c = await call(s, "comment_on_task", key="PAY-1", body_md="hello")
        assert not err and c["comment_id"]

    task = (await db.execute(select(Task))).scalar_one()
    events = (await db.execute(select(TaskEvent).where(TaskEvent.task_id == task.id))).scalars().all()
    kinds = {e.kind: e for e in events}
    assert {"created", "status_changed", "field_changed"} <= set(kinds)
    assert all(e.actor_user_id == manager.id for e in events)
    r = await client.get("/api/tasks/PAY-1/activity")
    assert any(i["type"] == "comment" and i["body_md"] == "hello" for i in r.json())


async def test_viewer_token_cannot_write(app, client, client_factory, db, mcp_running):
    viewer = await make_user(db, role=Role.viewer)
    await make_project(client, db, "PAY", viewer)
    mgr = await _mint(client)
    v = client_factory()
    await login(v, viewer)
    vsecret = await _mint(v)

    async with mcp_session(app, mgr) as s:
        await call(s, "create_task", project_key="PAY", title="x")
    async with mcp_session(app, vsecret) as s:
        err, tasks = await call(s, "list_tasks", project_key="PAY")
        assert not err and len(tasks) == 1
        for name, args in (
            ("create_task", {"project_key": "PAY", "title": "nope"}),
            ("update_task", {"key": "PAY-1", "title": "nope"}),
            ("move_task", {"key": "PAY-1", "column": "Done"}),
            ("comment_on_task", {"key": "PAY-1", "body_md": "nope"}),
        ):
            err, text = await call(s, name, **args)
            assert err and "forbidden" in text, name
