"""The worker loop: claim a job, run its handler in its own transaction, then complete or fail it."""

import asyncio
import contextlib
import logging

import asyncpg

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.events import _asyncpg_dsn
from app.jobs import queue
from app.jobs.models import Job

log = logging.getLogger(__name__)


async def run_once() -> bool:
    """Runs at most one job. Returns whether a job was claimed."""
    async with SessionLocal() as db:
        job = await queue.claim(db, set(queue.HANDLERS))
        await db.commit()
    if job is None:
        return False
    handler = queue.HANDLERS[job.kind]
    try:
        async with SessionLocal() as db:
            await handler(db, dict(job.payload))
            row = await db.get(Job, job.id, with_for_update=True)
            await queue.complete(db, row)
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - every handler failure is recorded on the job
        log.warning("job %s (%s) failed: %s", job.id, job.kind, exc)
        async with SessionLocal() as db:
            row = await db.get(Job, job.id, with_for_update=True)
            if row is not None:
                await queue.fail(db, row, f"{type(exc).__name__}: {exc}")
            await db.commit()
    return True


class _Wakeup:
    """LISTENs on the jobs channel with its own connection; falls back to polling while disconnected."""

    def __init__(self) -> None:
        self.event = asyncio.Event()
        self._conn: asyncpg.Connection | None = None

    async def connect(self) -> None:
        with contextlib.suppress(Exception):
            conn = await asyncpg.connect(_asyncpg_dsn(get_settings().database_url))
            await conn.add_listener(queue.CHANNEL, lambda *_: self.event.set())
            self._conn = conn

    async def ensure(self) -> None:
        if self._conn is None or self._conn.is_closed():
            self._conn = None
            await self.connect()

    async def close(self) -> None:
        if self._conn is not None and not self._conn.is_closed():
            with contextlib.suppress(Exception):
                await self._conn.close()


async def run_worker(stop: asyncio.Event, *, poll_seconds: float = 10.0) -> None:
    wake = _Wakeup()
    await wake.connect()
    try:
        while not stop.is_set():
            try:
                ran = await run_once()
            except Exception:
                log.exception("worker loop error")
                ran = False
            if ran:
                continue
            wake.event.clear()
            stopper = asyncio.create_task(stop.wait())
            woken = asyncio.create_task(wake.event.wait())
            await asyncio.wait({stopper, woken}, timeout=poll_seconds, return_when=asyncio.FIRST_COMPLETED)
            stopper.cancel()
            woken.cancel()
            await wake.ensure()
    finally:
        await wake.close()
