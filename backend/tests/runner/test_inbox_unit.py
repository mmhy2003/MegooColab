"""Inbox on a fake socket: what it reads is applied in order, and how the input ends (MC-214)."""

import asyncio
import json
import uuid

import app.runner.inbox as inbox_module
from app.runner.inbox import End, Inbox
from app.runner.protocol import AgentStatus, Heartbeat, RunFinished, RunSteerResult, RunUpdate
from app.runner.registry import RunnerConn


class _Socket:
    """receive() returns what the test puts on `frames`."""

    def __init__(self) -> None:
        self.frames: asyncio.Queue = asyncio.Queue()

    async def receive(self):
        return await self.frames.get()

    def text(self, payload) -> None:
        self.frames.put_nowait({"type": "websocket.receive", "text": json.dumps(payload)})

    def disconnect(self) -> None:
        self.frames.put_nowait({"type": "websocket.disconnect", "code": 1000})


RUN = uuid.uuid4()


def _update(seq: int) -> dict:
    return {"type": "run_update", "run_id": str(RUN), "seq": seq, "kind": "tool", "data": {"title": str(seq)}}


def _status() -> dict:
    return {"type": "agent_status", "agent_id": str(uuid.uuid4()), "available": True}


def _inbox(handle=None, handle_updates=None):
    sock = _Socket()
    applied: list = []

    async def _record(conn, msg):
        applied.append(msg)

    async def _record_updates(conn, updates):
        applied.extend(updates)

    inbox = Inbox(RunnerConn(uuid.uuid4(), uuid.uuid4(), sock), handle or _record, handle_updates or _record_updates)
    return inbox, sock, applied


async def _ended(inbox: Inbox) -> End:
    await asyncio.wait_for(inbox.worker, 2)
    return inbox.end


async def test_messages_are_applied_in_order():
    inbox, sock, applied = _inbox()
    sock.text(_update(1))
    sock.text({"type": "heartbeat"})
    sock.text(_status())
    sock.text(_update(2))
    sock.disconnect()
    inbox.start()
    await _ended(inbox)
    assert [type(m) for m in applied] == [RunUpdate, Heartbeat, AgentStatus, RunUpdate]
    assert [m.seq for m in applied if isinstance(m, RunUpdate)] == [1, 2]
    await inbox.stop()


async def test_an_invalid_frame_ends_the_input_after_what_came_before():
    inbox, sock, applied = _inbox()
    sock.text(_update(1))
    sock.text({"type": "no_such_message"})
    sock.text(_update(2))
    inbox.start()
    assert await _ended(inbox) == End(invalid=True)
    assert [m.seq for m in applied] == [1]
    await inbox.stop()


async def test_a_binary_frame_is_invalid():
    inbox, sock, applied = _inbox()
    sock.frames.put_nowait({"type": "websocket.receive", "bytes": b"x"})
    inbox.start()
    assert await _ended(inbox) == End(invalid=True)
    await inbox.stop()


async def test_a_disconnect_ends_the_input_as_valid():
    inbox, sock, applied = _inbox()
    sock.text({"type": "heartbeat"})
    sock.disconnect()
    inbox.start()
    assert await _ended(inbox) == End(invalid=False)
    assert len(applied) == 1
    await inbox.stop()


async def test_a_raising_handler_is_logged_and_the_next_message_is_applied(caplog):
    applied = []

    async def _handle(conn, msg):
        if isinstance(msg, Heartbeat):
            raise RuntimeError("boom")
        applied.append(msg)

    inbox, sock, _ = _inbox(handle=_handle)
    sock.text({"type": "heartbeat"})
    sock.text(_status())
    sock.disconnect()
    inbox.start()
    await _ended(inbox)
    assert [type(m) for m in applied] == [AgentStatus]
    assert "handling a message failed" in caplog.text
    await inbox.stop()


async def test_stop_lets_a_running_handler_finish():
    started, release = asyncio.Event(), asyncio.Event()
    finished = []

    async def _slow(conn, msg):
        started.set()
        await release.wait()
        finished.append(msg)

    inbox, sock, _ = _inbox(handle=_slow)
    sock.text({"type": "heartbeat"})
    inbox.start()
    await asyncio.wait_for(started.wait(), 2)
    stopping = asyncio.create_task(inbox.stop())
    await asyncio.sleep(0.05)
    assert not stopping.done()  # waits for the handler
    release.set()
    await asyncio.wait_for(stopping, 2)
    assert len(finished) == 1
    assert inbox.reader.done() and inbox.worker.done()


def _batching(monkeypatch):
    """An inbox that records each handler call: a list of seqs for a batch of updates, the message otherwise."""
    monkeypatch.setattr(inbox_module, "BATCH_MAX", 3)
    monkeypatch.setattr(inbox_module, "BATCH_WINDOW_SECONDS", 0.05)
    calls: list = []

    async def _one(conn, msg):
        calls.append(msg)

    async def _many(conn, updates):
        calls.append([u.seq for u in updates])

    inbox, sock, _ = _inbox(handle=_one, handle_updates=_many)
    return inbox, sock, calls


async def test_consecutive_updates_are_applied_in_batches_of_at_most_batch_max(monkeypatch):
    inbox, sock, calls = _batching(monkeypatch)
    for seq in range(1, 6):
        sock.text(_update(seq))
    sock.text({"type": "heartbeat"})
    sock.text(_update(6))
    sock.text(_update(7))
    sock.disconnect()
    inbox.start()
    await _ended(inbox)
    assert calls[:2] == [[1, 2, 3], [4, 5]]
    assert isinstance(calls[2], Heartbeat)
    assert calls[3:] == [[6, 7]]
    await inbox.stop()


async def test_updates_further_apart_than_the_window_are_separate_batches(monkeypatch):
    inbox, sock, calls = _batching(monkeypatch)
    sock.text(_update(1))
    inbox.start()
    await asyncio.sleep(0.2)
    sock.text(_update(2))
    sock.disconnect()
    await _ended(inbox)
    assert calls == [[1], [2]]
    await inbox.stop()


async def test_drain_applies_only_the_run_messages_left_after_stop_in_order(monkeypatch):
    inbox, sock, calls = _batching(monkeypatch)
    started, release = asyncio.Event(), asyncio.Event()

    async def _stalled(conn, msg):
        if isinstance(msg, Heartbeat):
            started.set()
            await release.wait()
        calls.append(msg)

    inbox._handle = _stalled
    sock.text({"type": "heartbeat"})  # being applied when stop() is called
    for seq in range(1, 5):
        sock.text(_update(seq))
    sock.text({"type": "hello", "runner_version": "0.1.0", "os": "linux", "arch": "amd64", "agents": []})
    sock.text({"type": "run_finished", "run_id": str(RUN), "outcome": "completed", "summary": "done"})
    sock.text(_status())
    sock.text(_update(5))
    sock.text({"type": "run_steer_result", "run_id": str(RUN), "message_id": str(uuid.uuid4()), "outcome": "injected"})
    inbox.start()
    await asyncio.wait_for(started.wait(), 2)
    await asyncio.sleep(0.05)  # everything is read
    stopping = asyncio.create_task(inbox.stop())
    await asyncio.sleep(0.05)
    release.set()
    await asyncio.wait_for(stopping, 2)
    assert len(calls) == 1 and isinstance(calls[0], Heartbeat)
    await inbox.drain()
    rest = calls[1:]
    assert rest[:2] == [[1, 2, 3], [4]]
    assert isinstance(rest[2], RunFinished)
    assert rest[3] == [5]
    assert isinstance(rest[4], RunSteerResult)
    assert len(rest) == 5
