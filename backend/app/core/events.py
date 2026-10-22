"""Live-update events: published inside DB transactions via NOTIFY, fanned out to subscribers.

NOTIFY is transactional, so an event is delivered only if the transaction that published it commits.
"""

import asyncio
import contextlib
import logging
import uuid

import asyncpg
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

CHANNEL = "megoo_events"


class Event(BaseModel):
    type: str
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


async def publish(db: AsyncSession, event: Event) -> None:
    await db.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHANNEL, "payload": event.model_dump_json()},
    )


def _asyncpg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class EventHub:
    """Listens on the NOTIFY channel with a dedicated connection and fans events out to queues."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._task: asyncio.Task | None = None
        self.ready = asyncio.Event()

    async def start(self, database_url: str) -> None:
        self.ready = asyncio.Event()
        self._task = asyncio.create_task(self._run(_asyncpg_dsn(database_url)))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(q)

    def _dispatch(self, _conn, _pid, _channel, payload: str) -> None:
        try:
            event = Event.model_validate_json(payload)
        except ValueError:
            log.warning("dropping malformed event payload")
            return
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("subscriber queue full; dropping event %s", event.type)

    async def _run(self, dsn: str) -> None:
        backoff = 0.5
        while True:
            conn = None
            try:
                conn = await asyncpg.connect(dsn)
                closed = asyncio.Event()
                conn.add_termination_listener(lambda _c: closed.set())
                await conn.add_listener(CHANNEL, self._dispatch)
                self.ready.set()
                backoff = 0.5
                await closed.wait()
                log.warning("event listener connection closed; reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("event listener failed; retrying in %.1fs", backoff)
            finally:
                if conn is not None and not conn.is_closed():
                    with contextlib.suppress(Exception):
                        await conn.close()
            self.ready.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


hub = EventHub()
