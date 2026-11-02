"""The worker reads the bot's messages itself (long polling), one poller at a time, from where it left off."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.core.crypto import encrypt
from app.core.db import SessionLocal, engine
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.telegram.client import TelegramError
from app.telegram.models import TelegramLink, TelegramLinkCode
from app.telegram.poller import POLL_LOCK, POLL_TIMEOUT, poll_once, run_telegram_poller
from tests.factories import make_user


async def _bot(db, offset=None) -> None:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    org.telegram_token_enc, org.telegram_bot_id, org.telegram_bot_username = encrypt("42:SECRET"), 42, "megoo_bot"
    org.telegram_offset = offset
    await db.commit()


async def _offset() -> int | None:
    async with SessionLocal() as s:
        return (await s.get(OrgSettings, ORG_SETTINGS_ID)).telegram_offset


async def _poll() -> bool:
    async with SessionLocal() as s:
        return await poll_once(s)


async def test_poll_once_handles_updates_and_moves_the_offset(db, org, telegram):
    await _bot(db)
    bea = await make_user(db, name="Bea")
    db.add(TelegramLinkCode(code="abc", user_id=bea.id, expires_at=datetime.now(UTC) + timedelta(minutes=5)))
    await db.commit()
    chat = {"id": 5001, "type": "private"}
    telegram.updates = [[{"update_id": 10, "message": {"chat": chat, "text": "/start abc"}},
                         {"update_id": 11, "message": {"chat": chat, "text": "hello"}}]]
    assert await _poll() is True
    assert telegram.update_calls[0] == {"token": "42:SECRET", "offset": None, "timeout": POLL_TIMEOUT}
    async with SessionLocal() as s:
        assert [link.chat_id for link in (await s.execute(select(TelegramLink))).scalars()] == [5001]
    assert await _offset() == 12
    assert await _poll() is True
    assert telegram.update_calls[1]["offset"] == 12


async def test_no_bot_no_poll(db, org, telegram):
    assert await _poll() is False
    assert telegram.update_calls == []


async def test_another_poller_is_left_alone(db, org, telegram):
    await _bot(db, offset=30)
    telegram.updates = [TelegramError(409, "Conflict: terminated by other getUpdates request")]
    assert await _poll() is False
    telegram.updates = [TelegramError(0, "could not reach Telegram (getUpdates)")]
    assert await _poll() is False
    assert await _offset() == 30


async def test_only_one_poller_holds_the_lock(db, org, telegram):
    await _bot(db)
    async with engine.connect() as holder:
        assert await holder.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": POLL_LOCK})
        stop = asyncio.Event()
        poller = asyncio.create_task(run_telegram_poller(stop))
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.wait_for(poller, 5)
        await holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": POLL_LOCK})
    assert telegram.update_calls == []


async def test_the_poller_polls_with_the_lock_and_stops(db, org, telegram):
    await _bot(db)
    stop = asyncio.Event()
    poller = asyncio.create_task(run_telegram_poller(stop))
    for _ in range(50):
        if telegram.update_calls:
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(poller, 5)
    assert telegram.update_calls
