"""Two-factor sign-in as a whole: an authenticator app, passkeys, or both; and the way back in when every second
factor is lost (an admin, or the server command, turns it off)."""

import logging
import uuid
from typing import Literal

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth.models import Passkey, User, WebauthnChallenge
from app.auth.service import try_send
from app.core.email import Mailer

log = logging.getLogger(__name__)


async def has_two_factor(db: AsyncSession, user: User) -> bool:
    if user.totp_enabled:
        return True
    return await db.scalar(select(Passkey.id).where(Passkey.user_id == user.id).limit(1)) is not None


async def two_factor_user_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Everyone with two-factor sign-in on."""
    rows = await db.execute(
        select(User.id)
        .where(or_(User.totp_enabled.is_(True), User.id.in_(select(Passkey.user_id))))
        .order_by(User.name)
    )
    return [uid for (uid,) in rows.all()]


async def reset_two_factor(
    db: AsyncSession, user: User, *, actor: User | None, via: Literal["admin", "cli"], mailer: Mailer | None
) -> None:
    """Removes the authenticator app and every passkey; the person signs in with the password alone and can set
    two-factor up again. Their sessions stay. They are told by email when email is set up."""
    user.totp_enabled = False
    user.totp_secret_enc = None
    await db.execute(delete(Passkey).where(Passkey.user_id == user.id))
    await db.execute(delete(WebauthnChallenge).where(WebauthnChallenge.user_id == user.id))
    await audit.record(
        db, "auth.two_factor_reset", actor_id=actor.id if actor else None, target_type="user", target_id=user.id,
        data={"via": via},
    )
    who = actor.name if actor else "An administrator"
    await try_send(
        mailer, user.email, "Two-factor sign-in turned off",
        f"{who} turned off two-factor sign-in for your MegooColab account. If you didn't ask for this, tell them.",
    )
