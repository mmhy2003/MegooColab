import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PersonalAccessToken, TokenScope, User, UserStatus
from app.auth.service import now
from app.core.events import Event, publish
from app.core.security import hash_token

TOKEN_PREFIX = "mgc_"
LAST_USED_EVERY = timedelta(minutes=1)

__all__ = [
    "TokenScope",
    "create_token",
    "hash_token",
    "resolve_bearer",
    "revoke_token",
    "revoke_user_tokens",
]


async def create_token(
    db: AsyncSession,
    user: User,
    name: str,
    scopes: list[TokenScope],
    expires_at: datetime | None,
) -> tuple[PersonalAccessToken, str]:
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = PersonalAccessToken(
        user_id=user.id,
        name=name,
        prefix=raw[:8],
        token_hash=hash_token(raw),
        scopes=[str(s) for s in scopes],
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return row, raw


async def resolve_bearer(
    db: AsyncSession, raw: str, scope: TokenScope | None = None
) -> tuple[User, PersonalAccessToken] | None:
    """The active user and token behind a raw bearer token, or None for any failure."""
    token = (
        await db.execute(
            select(PersonalAccessToken).where(PersonalAccessToken.token_hash == hash_token(raw))
        )
    ).scalar_one_or_none()
    if token is None or token.revoked_at is not None:
        return None
    ts = now()
    if token.expires_at is not None and token.expires_at <= ts:
        return None
    if scope is not None and str(scope) not in token.scopes:
        return None
    user = await db.get(User, token.user_id)
    if user is None or user.status != UserStatus.active:
        return None
    if token.last_used_at is None or ts - token.last_used_at >= LAST_USED_EVERY:
        token.last_used_at = ts
    return user, token


async def revoke_token(db: AsyncSession, token: PersonalAccessToken) -> None:
    from app.agents.service import unlink_tokens  # local: the agents service imports far more than auth may

    if token.revoked_at is None:
        token.revoked_at = now()
    await unlink_tokens(db, token.user_id, [token.id])
    # open runner sockets re-check their token
    await publish(db, Event(type="tokens.revoked", user_id=token.user_id))


async def revoke_user_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == user_id, PersonalAccessToken.revoked_at.is_(None))
        .values(revoked_at=now())
    )
    from app.agents.service import unlink_tokens  # local, as in revoke_token

    await unlink_tokens(db, user_id, None)
    await publish(db, Event(type="tokens.revoked", user_id=user_id))
