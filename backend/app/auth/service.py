import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Session, User
from app.core.config import get_settings
from app.core.security import hash_token, new_token

SESSION_COOKIE = "megoo_session"
SESSION_TTL = timedelta(days=14)
SESSION_SLIDE_EVERY = timedelta(hours=1)

MAX_FAILED_LOGINS = 10
FAILED_LOGIN_WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)


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
