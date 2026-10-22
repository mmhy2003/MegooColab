import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import OneTimeToken, Session, TokenPurpose, User
from app.core.config import get_settings
from app.core.email import Mailer
from app.core.security import hash_token, new_token

log = logging.getLogger(__name__)

SESSION_COOKIE = "megoo_session"
SESSION_TTL = timedelta(days=14)
SESSION_SLIDE_EVERY = timedelta(hours=1)

MAX_FAILED_LOGINS = 10
FAILED_LOGIN_WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)

TOKEN_TTL = {TokenPurpose.invite: timedelta(days=7), TokenPurpose.reset: timedelta(hours=1)}
TOKEN_PATH = {TokenPurpose.invite: "invite", TokenPurpose.reset: "reset"}


def now() -> datetime:
    return datetime.now(UTC)


async def create_session(db: AsyncSession, user: User, user_agent: str | None) -> str:
    token = new_token()
    ts = now()
    db.add(
        Session(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=ts + SESSION_TTL,
            last_seen_at=ts,
            user_agent=(user_agent or "")[:500] or None,
        )
    )
    return token


async def revoke_user_sessions(
    db: AsyncSession, user_id: uuid.UUID, except_token_hash: str | None = None
) -> None:
    stmt = delete(Session).where(Session.user_id == user_id)
    if except_token_hash:
        stmt = stmt.where(Session.token_hash != except_token_hash)
    await db.execute(stmt)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def is_locked(user: User) -> bool:
    return user.locked_until is not None and user.locked_until > now()


def register_failed_login(user: User) -> bool:
    """Count a failed attempt; returns True when this attempt locks the account."""
    ts = now()
    if user.last_failed_login_at is None or ts - user.last_failed_login_at > FAILED_LOGIN_WINDOW:
        user.failed_logins = 0
    user.failed_logins += 1
    user.last_failed_login_at = ts
    if user.failed_logins >= MAX_FAILED_LOGINS:
        user.locked_until = ts + LOCKOUT
        user.failed_logins = 0
        return True
    return False


def register_successful_login(user: User) -> None:
    user.failed_logins = 0
    user.last_failed_login_at = None
    user.locked_until = None
    user.last_login_at = now()


async def issue_token(db: AsyncSession, user: User, purpose: TokenPurpose) -> str:
    """Creates a single-use link token (older unused ones for the same purpose stop working)."""
    await db.execute(
        delete(OneTimeToken).where(
            OneTimeToken.user_id == user.id,
            OneTimeToken.purpose == purpose,
            OneTimeToken.used_at.is_(None),
        )
    )
    token = new_token()
    db.add(
        OneTimeToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(token),
            expires_at=now() + TOKEN_TTL[purpose],
        )
    )
    return token


def token_url(purpose: TokenPurpose, token: str) -> str:
    return f"{get_settings().public_url.rstrip('/')}/{TOKEN_PATH[purpose]}/{token}"


async def consume_token(db: AsyncSession, token: str, purpose: TokenPurpose) -> User:
    row = (
        await db.execute(
            select(OneTimeToken)
            .where(OneTimeToken.token_hash == hash_token(token), OneTimeToken.purpose == purpose)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at <= now():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_or_expired_token")
    row.used_at = now()
    user = await db.get(User, row.user_id)
    assert user is not None
    return user


async def try_send(mailer: Mailer | None, to: str, subject: str, body: str) -> bool:
    if mailer is None:
        return False
    try:
        await mailer.send(to, subject, body)
        return True
    except Exception:
        log.exception("sending email to %s failed", to)
        return False
