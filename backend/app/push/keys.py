"""The server's VAPID key pair: browsers accept push only from the key a device subscribed with. Made on first need,
so an admin has nothing to set up; the private key is stored encrypted with SECRET_KEY."""

import base64
import logging
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.push.models import PushSubscription

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VapidKeys:
    public_key: str  # base64url, no padding: what the browser subscribes with
    private_key_pem: str
    subject: str  # who to contact about this sender (push services ask for https: or mailto:)


def vapid_subject(public_url: str, smtp_from: str | None) -> str:
    if public_url.startswith("https://"):
        return public_url
    return f"mailto:{smtp_from or 'megoocolab@localhost'}"


def _new_pair() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return base64.urlsafe_b64encode(point).rstrip(b"=").decode(), pem


def _readable(org: OrgSettings) -> str | None:
    """The private key PEM, or None when there is none or it cannot be decrypted (SECRET_KEY changed)."""
    if org.vapid_public_key is None or org.vapid_private_key_enc is None:
        return None
    try:
        return decrypt(org.vapid_private_key_enc)
    except (InvalidToken, InvalidSignature, ValueError):
        return None


async def vapid_keys(db: AsyncSession) -> VapidKeys:
    """The key pair, made (and stored, uncommitted) when missing or unreadable. The caller commits."""
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    pem = _readable(org) if org is not None else None
    if pem is None:
        # locked, then read again: concurrent first calls agree on one pair
        org = (
            await db.execute(
                select(OrgSettings).where(OrgSettings.id == ORG_SETTINGS_ID).with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if org is None:  # never true once set up, and no one can sign in before that
            raise RuntimeError("push needs MegooColab to be set up first")
        pem = _readable(org)
        if pem is None:
            if org.vapid_private_key_enc is not None:
                # devices subscribed with the old key can never be reached again: they turn push on afresh
                log.warning("push: the stored VAPID key cannot be decrypted (SECRET_KEY changed?); made a new one")
                await db.execute(delete(PushSubscription))
            org.vapid_public_key, pem = _new_pair()
            org.vapid_private_key_enc = encrypt(pem)
            await db.flush()
    return VapidKeys(org.vapid_public_key, pem, vapid_subject(get_settings().public_url, org.smtp_from))
