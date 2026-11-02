"""The site's Telegram bot and the people linked to it."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core.crypto import decrypt, encrypt
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.telegram.client import TelegramError, get_client
from app.telegram.models import TelegramLink, TelegramLinkCode


async def org_settings(db: AsyncSession) -> OrgSettings:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    if org is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "setup_required")
    return org


async def bot_token(db: AsyncSession) -> str | None:
    """The bot's token, or None while the site has no bot."""
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    return decrypt(org.telegram_token_enc) if org is not None and org.telegram_token_enc else None


async def bot_username(db: AsyncSession) -> str | None:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    return org.telegram_bot_username if org is not None and org.telegram_token_enc else None


async def unlink(db: AsyncSession, user_id: uuid.UUID, *, reason: str, actor_id: uuid.UUID | None) -> None:
    """The person's chat no longer gets their notifications (their Telegram choices stay)."""
    link = await db.get(TelegramLink, user_id)
    if link is None:
        return
    await db.delete(link)
    await audit.record(db, "telegram.unlinked", actor_id=actor_id, target_type="user", target_id=user_id,
                       data={"reason": reason})


async def set_bot(db: AsyncSession, admin_id: uuid.UUID, token: str) -> str:
    """Checks the token with Telegram and makes it the site's bot; its @username. A different bot than before unlinks
    everyone (their chats belong to the old bot) and reads its messages from the start."""
    token = token.strip()
    try:
        me = await get_client().get_me(token)
    except TelegramError as exc:
        if exc.status == 0:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "telegram_unreachable") from None
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "telegram_token_refused") from None
    org = await org_settings(db)
    bot_id, username = int(me["id"]), str(me.get("username") or "")
    if org.telegram_bot_id is not None and org.telegram_bot_id != bot_id:
        for user_id in (await db.execute(select(TelegramLink.user_id))).scalars().all():
            await unlink(db, user_id, reason="bot_changed", actor_id=None)
        await db.execute(delete(TelegramLinkCode))
        org.telegram_offset = None
    org.telegram_token_enc = encrypt(token)
    org.telegram_bot_id, org.telegram_bot_username = bot_id, username
    await audit.record(db, "telegram.bot_set", actor_id=admin_id, target_type="org", data={"bot_username": username})
    return username


async def remove_bot(db: AsyncSession, admin_id: uuid.UUID) -> None:
    """Telegram stops for everyone. The bot's id stays, so setting the same bot again keeps people's links."""
    org = await org_settings(db)
    if org.telegram_token_enc is None:
        return
    org.telegram_token_enc = None
    await audit.record(db, "telegram.bot_removed", actor_id=admin_id, target_type="org",
                       data={"bot_username": org.telegram_bot_username})
