"""A runner connection's messages: read as they arrive, applied in order (MC-214).

The reader is the only caller of ws.receive(): it notes that the runner is alive, validates each frame and queues it,
so the socket keeps being read (and uvicorn keeps answering pings) however slow the database is. The worker applies
the messages one at a time, in order, and takes consecutive run updates as one batch."""

import asyncio
import contextlib
import itertools
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.runner.protocol import RunFinished, RunSteerResult, RunUpdate, runner_message
from app.runner.registry import RunnerConn

log = logging.getLogger(__name__)

# module-level so tests can monkeypatch them small
INBOX_MAX = 2000
BATCH_WINDOW_SECONDS = 0.25
BATCH_MAX = 200
# what a connection that ended still applies (Inbox.drain)
RUN_MESSAGES = (RunUpdate, RunFinished, RunSteerResult)


@dataclass(frozen=True)
class End:
    """The end of the runner's input: it went away, or sent a frame that is not a valid message (invalid)."""

    invalid: bool


def _parse(text: str | None):
    if text is None:
        return End(invalid=True)
    try:
        return runner_message.validate_python(json.loads(text))
    except (ValueError, ValidationError):
        return End(invalid=True)


class Inbox:
    def __init__(self, conn: RunnerConn, handle: Callable[[RunnerConn, object], Awaitable[None]],
                 handle_updates: Callable[[RunnerConn, list[RunUpdate]], Awaitable[None]]) -> None:
        self.conn = conn
        self._handle, self._handle_updates = handle, handle_updates
        self._queue: asyncio.Queue = asyncio.Queue(INBOX_MAX)
        self._taken: list = []  # off the queue, not applied yet: a batch being collected and what ended it
        self._busy = False  # a handler is running
        self._stopping = False
        self.end: End | None = None  # set when the worker reached the end of the input
        self.reader: asyncio.Task | None = None
        self.worker: asyncio.Task | None = None

    def start(self) -> None:
        self.reader = asyncio.create_task(self._read())
        self.worker = asyncio.create_task(self._work())

    async def _read(self) -> None:
        warned = False
        try:
            while True:
                message = await self.conn.socket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                self.conn.touch()
                item = _parse(message.get("text"))
                if self._queue.full() and not warned:
                    warned = True
                    log.warning("runner %s: %d messages wait to be applied; reading pauses", self.conn.token_id,
                                INBOX_MAX)
                await self._queue.put(item)
                if isinstance(item, End):
                    return
        except Exception:  # the socket is gone: starlette raises once it is closed
            pass
        await self._queue.put(End(invalid=False))

    async def _work(self) -> None:
        while not self._stopping:
            if not self._taken:
                self._taken.append(await self._queue.get())
            first = self._taken[0]
            if isinstance(first, End):
                self.end = first
                return
            if isinstance(first, RunUpdate):
                await self._collect()
                n = sum(1 for _ in itertools.takewhile(lambda m: isinstance(m, RunUpdate), self._taken))
                await self._apply(self._handle_updates, self._taken[:n], n)
            else:
                await self._apply(self._handle, first, 1)

    async def _collect(self) -> None:
        """More run updates after the first: until another message is next, BATCH_MAX are taken or the window closes."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + BATCH_WINDOW_SECONDS
        while len(self._taken) < BATCH_MAX and isinstance(self._taken[-1], RunUpdate):
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            try:
                async with asyncio.timeout(remaining):
                    self._taken.append(await self._queue.get())
            except TimeoutError:
                return

    async def _apply(self, handler, arg, n: int) -> None:
        self._busy = True
        try:
            await handler(self.conn, arg)
        except Exception:
            log.exception("runner: handling a message failed")
        finally:
            del self._taken[:n]
            self._busy = False

    async def stop(self) -> None:
        """Stop reading. A message being applied is finished first; what is left waits for drain()."""
        self._stopping = True
        for task in (self.reader,):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        if self.worker is not None:
            if not self._busy:
                self.worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.worker

    async def drain(self) -> None:
        """After stop(): apply the run messages still waiting, in order, so a run_finished that arrived before the
        connection ended is not lost. Anything else describes a connection that is gone and is dropped."""
        items = list(self._taken)
        self._taken.clear()
        while not self._queue.empty():
            items.append(self._queue.get_nowait())
        items = [m for m in items if isinstance(m, RUN_MESSAGES)]
        i = 0
        while i < len(items):
            if isinstance(items[i], RunUpdate):
                j = i
                while j < len(items) and j - i < BATCH_MAX and isinstance(items[j], RunUpdate):
                    j += 1
                await self._apply(self._handle_updates, items[i:j], 0)
                i = j
            else:
                await self._apply(self._handle, items[i], 0)
                i += 1
