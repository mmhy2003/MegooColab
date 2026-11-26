"""The runner socket over a real uvicorn server: a slow database does not close it (MC-214)."""

import asyncio
import json
import time

from sqlalchemy import func, select
from websockets.protocol import State

import app.runner.router as rr
from app.core.db import SessionLocal
from app.tasks.models import TaskEvent
from tests.runner.live import live_server, running_runs, runner_socket


def _stall(monkeypatch) -> asyncio.Event:
    """Run messages wait (as on an empty DB pool) until the returned event is set."""
    release = asyncio.Event()
    original = rr._on_this_machine

    async def _stalled(conn, run_id):
        await release.wait()
        return await original(conn, run_id)

    monkeypatch.setattr(rr, "_on_this_machine", _stalled)
    return release


def _tool(run_id, seq: int) -> str:
    return json.dumps({
        "type": "run_update", "run_id": str(run_id), "seq": seq, "kind": "tool",
        "data": {"tool_kind": "read", "title": f"Read {seq}", "status": "completed"},
    })


async def _tool_events() -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(TaskEvent).where(TaskEvent.kind == "agent_tool"))


async def test_a_stalled_handler_does_not_close_the_runner_socket(client, db, monkeypatch):
    """Acceptance 1: run messages stalled far longer than the ping timeout; the socket stays open and answers pings."""
    _user, headers, [run_id] = await running_runs(client, db, 1)
    release = _stall(monkeypatch)
    async with live_server() as base:
        try:
            async with runner_socket(base, headers) as ws:
                for seq in range(1, 101):
                    await ws.send(_tool(run_id, seq))
                await asyncio.sleep(2)  # five ping timeouts
                assert ws.state is State.OPEN, ws.close_code
                await asyncio.wait_for(await ws.ping(), 1)  # the server still reads and answers
                release.set()
                # one transaction per update for now, each with fresh connections on the tests' NullPool (~0.15 s)
                deadline = time.monotonic() + 30
                while await _tool_events() < 100:
                    assert time.monotonic() < deadline, f"{await _tool_events()} of 100 updates applied"
                    await asyncio.sleep(0.1)
                assert ws.state is State.OPEN, ws.close_code
        finally:
            release.set()


async def test_a_slow_handler_is_not_closed_as_idle_while_frames_arrive(client, db, monkeypatch):
    _user, headers, [run_id] = await running_runs(client, db, 1)
    monkeypatch.setattr(rr, "IDLE_TIMEOUT_SECONDS", 0.5)
    release = _stall(monkeypatch)
    async with live_server() as base:
        try:
            async with runner_socket(base, headers) as ws:
                await ws.send(_tool(run_id, 1))
                for _ in range(15):
                    await ws.send(json.dumps({"type": "heartbeat"}))
                    await asyncio.sleep(0.1)
                assert ws.state is State.OPEN, ws.close_code
        finally:
            release.set()
