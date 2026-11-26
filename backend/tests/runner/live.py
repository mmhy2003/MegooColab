"""A real uvicorn server for runner socket tests (MC-214): the keepalive pings and the frame queue only exist there,
not in the TestClient."""

import asyncio
import contextlib
import socket
import uuid

import uvicorn
from sqlalchemy import update
from websockets.asyncio.client import connect

from app.agent_runs.models import AgentRun
from app.auth.models import User
from app.main import create_app
from tests.agent_runs.test_dispatch import queue_run
from tests.factories import login, make_project, make_user


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def live_server(ping_interval: float = 0.2, ping_timeout: float = 0.4, max_queue: int = 4):
    """The app on a free port, with short keepalive pings; yields its ws:// base URL. It runs websockets-sansio, what
    uvicorn's ws=auto (the Dockerfile's) picks: it stops reading the socket until the app receives the last frame, so
    an app that stops receiving misses the pongs. (max_queue only matters to the legacy websockets implementation.)"""
    port = _free_port()
    config = uvicorn.Config(
        create_app(), host="127.0.0.1", port=port, ws="websockets-sansio", ws_ping_interval=ping_interval,
        ws_ping_timeout=ping_timeout, ws_max_queue=max_queue, lifespan="on", log_level="warning",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):
            while not server.started:
                assert not task.done(), "the server did not start"
                await asyncio.sleep(0.02)
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)


async def running_runs(client, db, n: int) -> tuple[User, dict, list[uuid.UUID]]:
    """n running runs of one agent linked to a fresh runner token; returns the user, that token's auth headers and
    the run ids."""
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    r = await client.post("/api/tokens", json={"name": "laptop", "scopes": ["runner"]})
    assert r.status_code == 201, r.text
    token = r.json()
    r = await client.post(
        "/api/agents",
        json={"program": "claude_code", "max_concurrent_runs": n, "runner_token_id": token["token"]["id"]},
    )
    assert r.status_code == 201, r.text
    agent = r.json()
    r = await client.put(
        f"/api/agents/{agent['id']}/bindings", json={"bindings": [{"project_ref": "PAY", "local_path": "/repo"}]}
    )
    assert r.status_code == 200, r.text
    run_ids = []
    for i in range(n):
        t = (await client.post("/api/projects/PAY/tasks", json={"title": f"T{i}", "assignee_agent_id": agent["id"]}))
        assert t.status_code == 201, t.text
        run_ids.append(uuid.UUID((await queue_run(t.json()["key"]))["id"]))
    await db.execute(update(AgentRun).where(AgentRun.id.in_(run_ids)).values(status="running"))
    await db.commit()
    return me, {"Authorization": f"Bearer {token['secret']}"}, run_ids


@contextlib.asynccontextmanager
async def runner_socket(ws_base: str, headers: dict):
    """A runner's socket without client pings, and a task that reads every frame (into ws.received) so the client
    side never stops reading."""
    async with connect(ws_base + "/api/runner/ws", additional_headers=headers, ping_interval=None) as ws:
        ws.received = []

        async def _read():
            with contextlib.suppress(Exception):
                async for frame in ws:
                    ws.received.append(frame)

        reader = asyncio.create_task(_read())
        try:
            yield ws
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
