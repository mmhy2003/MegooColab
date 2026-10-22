from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from app.auth.models import Role, Session, User, UserStatus
from app.auth.service import SESSION_COOKIE, SESSION_SLIDE_EVERY, SESSION_TTL, now
from app.core.db import DbSession
from app.core.security import hash_token


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")


async def current_session(request: Request, db: DbSession) -> Session:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthorized()
    session = (
        await db.execute(select(Session).where(Session.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    ts = now()
    if session is None or session.expires_at <= ts:
        raise _unauthorized()
    if ts - session.last_seen_at >= SESSION_SLIDE_EVERY:
        session.last_seen_at = ts
        session.expires_at = ts + SESSION_TTL
    return session


async def current_user(
    db: DbSession, session: Annotated[Session, Depends(current_session)]
) -> User:
    user = await db.get(User, session.user_id)
    if user is None or user.status != UserStatus.active:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def require_password_ok(user: CurrentUser) -> User:
    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password_change_required")
    return user


AuthedUser = Annotated[User, Depends(require_password_ok)]


def require_roles(*roles: Role) -> Callable[..., Awaitable[User]]:
    async def _dep(user: AuthedUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
        return user

    return _dep


AdminUser = Annotated[User, Depends(require_roles(Role.admin))]
