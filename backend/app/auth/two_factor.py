"""Two-factor sign-in as a whole: an authenticator app, passkeys, or both; and the way back in when every second
factor is lost (an admin, or the server command, turns it off)."""

from typing import Literal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth.models import Passkey, User, WebauthnChallenge
from app.auth.service import try_send
from app.core.config import get_settings
from app.core.email import Mailer, org_name
from app.core.email_template import Email, render



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
    text, html = render(Email(
        tag="Security", tone="pink", heading="Two-factor sign-in was turned off",
        paragraphs=[f"{who} turned off two-factor sign-in for your MegooColab account.",
                    "You can sign in with your password alone now. If you didn't ask for this, tell your admin straight "
                    "away."],
        button=("Set up two-factor again", f"{get_settings().public_url}/settings/profile?tab=two-factor"),
        footer="A security notice about your MegooColab account. It's always sent.",
    ), org=await org_name(db))
    await try_send(mailer, user.email, "Two-factor sign-in turned off", text, html)
