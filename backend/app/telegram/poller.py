"""Hearing the bot's messages: the worker asks Telegram for them itself (long polling), so no inbound connection is
needed. Telegram allows one reader per bot, so only the worker holding a Postgres advisory lock polls."""

import asyncio
import contextlib
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, engine
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.telegram import service
from app.telegram.client import TelegramError, get_client

log = logging.getLogger(__name__)

POLL_LOCK = 727_101  # pg advisory lock key: the one Telegram reader
POLL_TIMEOUT = 25  # seconds Telegram holds a getUpdates open when there is nothing new
IDLE_SECONDS = 30  # between tries with no bot, without the lock, or after a failed poll
MIN_ROUND = 1.0  # a poll answered at once is not repeated sooner than this


async def poll_once(db: AsyncSession) -> bool:
    """Reads and handles the bot's new messages; False when there is no bot or Telegram could not be read."""
    token = await service.bot_token(db)
    offset = (await db.get(OrgSettings, ORG_SETTINGS_ID)).telegram_offset if token is not None else None
    # nothing waits in a transaction while Telegram holds the poll open (a migration altering org_settings would
    # queue behind it)
    await db.commit()
    if token is None:
        return False
    try:
        updates = await get_client().get_updates(token, offset, POLL_TIMEOUT)
    except TelegramError as exc:
        log.warning("telegram: reading the bot's messages failed (%s)", exc.status)
        return False
    for update in updates:
        try:
            await service.handle_update(db, token, update)
        except Exception:  # one bad message must not stop the others
            await db.rollback()
            log.exception("telegram: a message to the bot could not be handled")
        org = await db.get(OrgSettings, ORG_SETTINGS_ID)
        org.telegram_offset = int(update["update_id"]) + 1
        await db.commit()
    return True


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), seconds)


async def _poll_while_holding(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        started = loop.time()
        async with SessionLocal() as db:
            polling = asyncio.create_task(poll_once(db))
            stopping = asyncio.create_task(stop.wait())
            await asyncio.wait({polling, stopping}, return_when=asyncio.FIRST_COMPLETED)
            stopping.cancel()
            if not polling.done():  # stopping: a long poll in progress is dropped
                polling.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await polling
                return
            polled = polling.result()
        await _wait(stop, IDLE_SECONDS if not polled else max(0.0, MIN_ROUND - (loop.time() - started)))


async def run_telegram_poller(stop: asyncio.Event) -> None:
    """Runs beside the worker's job loop until `stop` is set."""
    while not stop.is_set():
        try:
            async with engine.connect() as pooled:
                # autocommit: the lock is held by the session, so the connection never sits in a transaction
                conn = await pooled.execution_options(isolation_level="AUTOCOMMIT")
                if await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": POLL_LOCK}):
                    try:
                        await _poll_while_holding(stop)
                    finally:
                        await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": POLL_LOCK})
        except Exception:  # the poller keeps going; jobs are not affected
            log.exception("telegram: the poller failed")
        await _wait(stop, IDLE_SECONDS)
