"""The site's Telegram bot and the people linked to it."""

import html
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth.models import User, UserStatus
from app.core.crypto import decrypt, encrypt
from app.notifications.models import DEFAULT_PREFS, Kind, NotificationPref
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.telegram.client import TelegramError, get_client
from app.telegram.models import TelegramLink, TelegramLinkCode

log = logging.getLogger(__name__)

CODE_LIFETIME = timedelta(minutes=15)
CONNECTED = "Connected to MegooColab as {name}."
EXPIRED = "This link has expired. Open MegooColab › Settings › Notifications and press Connect Telegram again."
ONLY_NOTIFICATIONS = "This bot only sends MegooColab notifications."
# when someone links for the first time and gets no push at all
FIRST_LINK_KINDS = (Kind.needs_you, Kind.mentioned)


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
        # a bot left with a webhook (used elsewhere before) cannot be polled: Telegram answers getUpdates with 409
        await get_client().delete_webhook(token)
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


# ---- a person's link ---------------------------------------------------------------------------------------------


async def link_url(db: AsyncSession, user_id: uuid.UUID) -> str:
    """A Start link with a new one-time code for this person."""
    username = await bot_username(db)
    if username is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "telegram_not_set")
    code = secrets.token_urlsafe(24)
    db.add(TelegramLinkCode(code=code, user_id=user_id, expires_at=datetime.now(UTC) + CODE_LIFETIME))
    return f"https://t.me/{username}?start={code}"


async def is_linked(db: AsyncSession, user_id: uuid.UUID) -> bool:
    return await db.get(TelegramLink, user_id) is not None


async def apply_first_link_defaults(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Telegram on for the kinds the person gets as push (or, with none, needs-you and mentions) — only the first
    time: someone who already chose Telegram for any kind keeps their choices."""
    rows = {p.kind: p for p in (await db.execute(
        select(NotificationPref).where(NotificationPref.user_id == user_id))).scalars()}
    current = {k: (rows[k].in_app, rows[k].email, rows[k].push, rows[k].telegram) if k in rows else DEFAULT_PREFS[k]
               for k in Kind}
    if any(v[3] for v in current.values()):
        return
    kinds = [k for k, v in current.items() if v[2]] or list(FIRST_LINK_KINDS)
    for k in kinds:
        in_app, email, push, _ = current[k]
        stmt = insert(NotificationPref).values(user_id=user_id, kind=k, in_app=in_app, email=email, push=push,
                                               telegram=True)
        await db.execute(stmt.on_conflict_do_update(index_elements=["user_id", "kind"], set_={"telegram": True}))


async def _reply(token: str, chat_id: int, text: str) -> None:
    try:
        await get_client().send_message(token, chat_id, text, None)
    except TelegramError as exc:
        log.warning("telegram: a reply to a chat failed (%s)", exc.status)


async def _link(db: AsyncSession, token: str, chat_id: int, code: str) -> None:
    row = await db.get(TelegramLinkCode, code, with_for_update=True) if code else None
    user = await db.get(User, row.user_id) if row is not None else None
    if row is not None:
        await db.delete(row)  # used or expired, it is gone
    if row is None or row.expires_at <= datetime.now(UTC) or user is None or user.status != UserStatus.active:
        await db.flush()
        await _reply(token, chat_id, EXPIRED)
        return
    holder = await db.scalar(select(TelegramLink.user_id).where(TelegramLink.chat_id == chat_id))
    if holder is not None and holder != user.id:
        await unlink(db, holder, reason="moved", actor_id=None)
        await db.flush()  # the chat is free before it is linked again
    link = await db.get(TelegramLink, user.id)
    if link is None:
        db.add(TelegramLink(user_id=user.id, chat_id=chat_id))
    else:
        link.chat_id, link.linked_at = chat_id, datetime.now(UTC)
    await apply_first_link_defaults(db, user.id)
    await audit.record(db, "telegram.linked", actor_id=user.id, target_type="user", target_id=user.id)
    await db.flush()
    await _reply(token, chat_id, CONNECTED.format(name=html.escape(user.name, quote=False)))  # sent as HTML


async def handle_update(db: AsyncSession, token: str, update: dict) -> None:
    """One message to the bot: only a private chat's are answered; `/start <code>` links that chat."""
    message = update.get("message")
    chat = (message or {}).get("chat") or {}
    if not message or chat.get("type") != "private" or "id" not in chat:
        return
    chat_id, text = int(chat["id"]), str(message.get("text") or "").strip()
    command, _, rest = text.partition(" ")
    if command == "/start":
        await _link(db, token, chat_id, rest.strip()[:64])
    else:
        await _reply(token, chat_id, ONLY_NOTIFICATIONS)
