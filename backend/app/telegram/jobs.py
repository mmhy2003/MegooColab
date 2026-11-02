"""Worker job: one notification to one person's Telegram chat (a send that raises fails the job, which the queue
retries)."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserStatus
from app.core.config import get_settings
from app.jobs import queue
from app.telegram import service
from app.telegram.client import TelegramError, get_client
from app.telegram.messages import button_url, full_url, message_text
from app.telegram.models import TelegramLink

log = logging.getLogger(__name__)

RETRY_AFTER_DEFAULT = 30  # seconds, when Telegram asks to slow down without saying for how long


def _about_the_button(exc: TelegramError) -> bool:
    words = exc.description.lower()
    return exc.status == 400 and ("button" in words or "url" in words)


@queue.register("notify.telegram")
async def send_telegram(db: AsyncSession, payload: dict) -> None:
    user_id = uuid.UUID(str(payload["user_id"]))
    token = await service.bot_token(db)
    link = await db.get(TelegramLink, user_id)
    user = await db.get(User, user_id)
    if token is None or link is None or user is None or user.status != UserStatus.active:
        return
    public = get_settings().public_url
    button = button_url(public, payload["link"])
    client = get_client()
    try:
        try:
            await client.send_message(token, link.chat_id,
                                      message_text(payload["title"], payload["body"], None if button else
                                                   full_url(public, payload["link"])), button)
        except TelegramError as exc:
            if not (button and _about_the_button(exc)):
                raise
            # Telegram would not take the button: the address goes in the text instead
            await client.send_message(token, link.chat_id, message_text(
                payload["title"], payload["body"], full_url(public, payload["link"])), None)
    except TelegramError as exc:
        if exc.status == 403:
            await service.unlink(db, user_id, reason="blocked", actor_id=None)
        elif exc.status == 400 and "chat not found" in exc.description.lower():
            await service.unlink(db, user_id, reason="chat_gone", actor_id=None)
        elif exc.status == 429:
            wait = exc.retry_after if exc.retry_after is not None else RETRY_AFTER_DEFAULT
            await queue.enqueue(db, "notify.telegram", payload, run_after=datetime.now(UTC) + timedelta(seconds=wait))
        elif exc.status == 0 or exc.status >= 500:
            raise
        else:  # the message itself was refused: sending it again would not help
            log.warning("telegram: dropped a notification Telegram refused with %s", exc.status)
