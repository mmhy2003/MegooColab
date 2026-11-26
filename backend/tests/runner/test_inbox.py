"""The runner socket over a real uvicorn server: a slow database does not close it (MC-214)."""

import asyncio
import json
import threading
import time

from sqlalchemy import func, select

from app.agent_runs.models import AgentRun
from websockets.protocol import State

import app.runner.router as rr
from app.core.db import SessionLocal
from app.tasks.models import TaskEvent
from tests.agent_runs.test_dispatch import _avail, _setup, _start, _wait_run
from tests.runner.live import live_server, running_runs, runner_socket
from tests.runner.test_runner_ws import URL, _expect_close, _hello, _manager_with_project


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
                # the stalled updates are applied in batches now, each in one transaction
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


async def test_two_runs_streaming_on_one_socket_both_finish(client, db, monkeypatch):
    """Acceptance 2: two runs stream at once on one runner over a slow database; both finish, the socket stays open,
    and each run's updates keep their order."""
    _user, headers, runs = await running_runs(client, db, 2)
    original = rr.apply_updates

    async def _slow(db, conn_user_id, updates):
        await asyncio.sleep(0.3)
        return await original(db, conn_user_id, updates)

    monkeypatch.setattr(rr, "apply_updates", _slow)
    async with live_server() as base:
        async with runner_socket(base, headers) as ws:
            for seq in range(1, 51):
                for run_id in runs:
                    await ws.send(_tool(run_id, seq))
            for run_id in runs:
                await ws.send(json.dumps({"type": "run_finished", "run_id": str(run_id), "outcome": "completed", "summary": "done"}))
            deadline = time.monotonic() + 10
            while True:
                async with SessionLocal() as s:
                    statuses = (await s.execute(select(AgentRun.status).where(AgentRun.id.in_(runs)))).scalars().all()
                if all(st == "completed" for st in statuses):
                    break
                assert time.monotonic() < deadline, statuses
                await asyncio.sleep(0.1)
            assert ws.state is State.OPEN, ws.close_code
    async with SessionLocal() as s:
        events = (await s.execute(
            select(TaskEvent).where(TaskEvent.kind == "agent_tool").order_by(TaskEvent.created_at, TaskEvent.id)
        )).scalars().all()
    for run_id in runs:
        titles = [e.data["title"] for e in events if e.data["run_id"] == str(run_id)]
        assert titles == [f"Read {seq}" for seq in range(1, 51)]


def _stall_threaded(monkeypatch) -> threading.Event:
    """As _stall, for TestClient tests: the app's loop runs in another thread, so the test sets a threading.Event."""
    release = threading.Event()
    original = rr._on_this_machine

    async def _stalled(conn, run_id):
        while not release.is_set():
            await asyncio.sleep(0.01)
        return await original(conn, run_id)

    monkeypatch.setattr(rr, "_on_this_machine", _stalled)
    return release


def _queue_finished_behind_a_stalled_update(tc, ws, agent, task, monkeypatch) -> tuple[dict, threading.Event]:
    """The run is running; its update stalls in the worker and its run_finished (completed) waits behind it."""
    run = _start(tc, task)
    ws.receive_json()
    ws.send_json(_hello([_avail(agent)]))
    assert ws.receive_json()["run_id"] == run["id"]
    _wait_run(tc, task, run["id"], "running")
    release = _stall_threaded(monkeypatch)
    ws.send_text(_tool(run["id"], 1))
    ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "completed", "summary": "done"})
    time.sleep(0.3)  # both are read and queued
    return run, release


async def test_a_run_finished_queued_before_the_socket_is_replaced_completes_the_run(db, tc_factory, monkeypatch):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    release = threading.Event()
    try:
        with tc.websocket_connect(URL, headers=token["headers"]) as first:
            run, release = _queue_finished_behind_a_stalled_update(tc, first, agent, task, monkeypatch)
            with tc.websocket_connect(URL, headers=token["headers"]) as second:
                second.receive_json()
                _expect_close(first, 4409)
                release.set()
                _wait_run(tc, task, run["id"], "completed")
    finally:
        release.set()
    out = tc.get(f"/api/tasks/{task['key']}/agent-runs").json()[0]
    assert out["status"] == "completed" and out["reason"] is None


async def test_unauthorized_close_applies_nothing(db, tc_factory, monkeypatch):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    release = threading.Event()
    try:
        with tc.websocket_connect(URL, headers=token["headers"]) as ws:
            run, release = _queue_finished_behind_a_stalled_update(tc, ws, agent, task, monkeypatch)
            assert tc.delete(f"/api/tokens/{token['id']}").status_code == 204
            _expect_close(ws, 4401)
            release.set()
        _wait_run(tc, task, run["id"], "cancelled")
        time.sleep(0.3)  # cleanup has run; nothing queued may end the run another way
    finally:
        release.set()
    out = tc.get(f"/api/tasks/{task['key']}/agent-runs").json()[0]
    assert out["status"] == "cancelled" and out["reason"] == "runner_unauthorized"
