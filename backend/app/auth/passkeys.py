"""Passkeys (WebAuthn) as a second sign-in factor: options, challenges and verification, on py_webauthn."""

import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import options_to_json_dict, parse_authentication_credential_json, parse_authenticator_data
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.audit import service as audit
from app.auth.models import ChallengePurpose, Passkey, User, WebauthnChallenge
from app.auth.service import now
from app.core.config import get_settings
from app.org.models import ORG_SETTINGS_ID, OrgSettings

MAX_PASSKEYS = 10
CHALLENGE_TTL = timedelta(minutes=5)
TIMEOUT_MS = 120_000
ALGORITHMS = [COSEAlgorithmIdentifier.ECDSA_SHA_256, COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256]


class PasskeyError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def rp_id() -> str:
    """The server's host name: passkeys belong to it (a new address makes them stop working)."""
    return urlsplit(get_settings().public_url).hostname or "localhost"  # hostname is lowercased


def expected_origin() -> str:
    """PUBLIC_URL's origin as a browser writes it: lowercase host, no default port."""
    parts = urlsplit(get_settings().public_url)
    scheme = parts.scheme.lower()
    port = parts.port
    default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    return f"{scheme}://{rp_id()}" + (f":{port}" if port and not default else "")


async def new_challenge(db: AsyncSession, user_id: uuid.UUID, purpose: ChallengePurpose) -> bytes:
    """A fresh challenge, replacing the person's open one for this purpose; expired ones go."""
    await db.execute(
        delete(WebauthnChallenge).where(
            (WebauthnChallenge.expires_at < now())
            | ((WebauthnChallenge.user_id == user_id) & (WebauthnChallenge.purpose == purpose))
        )
    )
    challenge = uuid.uuid4().bytes + uuid.uuid4().bytes
    db.add(WebauthnChallenge(user_id=user_id, purpose=purpose, challenge=challenge, expires_at=now() + CHALLENGE_TTL))
    await db.flush()
    return challenge


async def take_challenge(db: AsyncSession, user_id: uuid.UUID, purpose: ChallengePurpose) -> bytes | None:
    """The open challenge, used up: it is gone whatever the answer. None when there is none or it expired."""
    row = (
        await db.execute(
            delete(WebauthnChallenge)
            .where(WebauthnChallenge.user_id == user_id, WebauthnChallenge.purpose == purpose)
            .returning(WebauthnChallenge.challenge, WebauthnChallenge.expires_at)
        )
    ).first()
    if row is None or row.expires_at < now():
        return None
    return row.challenge


async def list_passkeys(db: AsyncSession, user_id: uuid.UUID) -> list[Passkey]:
    rows = await db.execute(select(Passkey).where(Passkey.user_id == user_id).order_by(Passkey.created_at, Passkey.id))
    return list(rows.scalars())


async def _rp_name(db: AsyncSession) -> str:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    return org.name if org and org.name else "MegooColab"


def _descriptors(passkeys: list[Passkey]) -> list[PublicKeyCredentialDescriptor]:
    out = []
    for p in passkeys:
        transports = []
        for t in p.transports or []:
            try:
                transports.append(AuthenticatorTransport(t))
            except ValueError:
                continue  # one the library doesn't know: leave it out
        out.append(PublicKeyCredentialDescriptor(id=p.credential_id, transports=transports or None))
    return out


async def registration_options(db: AsyncSession, user: User) -> dict:
    existing = await list_passkeys(db, user.id)
    if len(existing) >= MAX_PASSKEYS:
        raise PasskeyError("too_many_passkeys")
    options = generate_registration_options(
        rp_id=rp_id(),
        rp_name=await _rp_name(db),
        user_id=user.id.bytes,
        user_name=user.email,
        user_display_name=user.name,
        challenge=await new_challenge(db, user.id, ChallengePurpose.register),
        timeout=TIMEOUT_MS,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=_descriptors(existing),
        supported_pub_key_algs=ALGORITHMS,
    )
    return options_to_json_dict(options)


async def register(db: AsyncSession, user: User, name: str, credential: dict) -> Passkey:
    challenge = await take_challenge(db, user.id, ChallengePurpose.register)
    if challenge is None:
        raise PasskeyError("passkey_invalid")
    if await db.scalar(select(func.count()).select_from(Passkey).where(Passkey.user_id == user.id)) >= MAX_PASSKEYS:
        raise PasskeyError("too_many_passkeys")
    try:
        verified = verify_registration_response(
            credential=credential, expected_challenge=challenge, expected_rp_id=rp_id(),
            expected_origin=expected_origin(), supported_pub_key_algs=ALGORITHMS,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError) as err:  # garbled JSON included: refused, not a crash
        raise PasskeyError("passkey_invalid") from err
    if await db.scalar(select(Passkey.id).where(Passkey.credential_id == verified.credential_id)) is not None:
        raise PasskeyError("passkey_exists")
    response = credential.get("response") if isinstance(credential, dict) else None
    transports = response.get("transports") if isinstance(response, dict) else None
    passkey = Passkey(
        user_id=user.id, credential_id=verified.credential_id, public_key=verified.credential_public_key,
        sign_count=verified.sign_count, name=name,
        transports=[t for t in transports if isinstance(t, str)][:10] if isinstance(transports, list) else [],
        aaguid=str(verified.aaguid) if verified.aaguid else None,
    )
    db.add(passkey)
    await db.flush()
    await audit.record(db, "auth.passkey_added", actor_id=user.id, target_type="user", target_id=user.id,
                       data={"name": name})
    return passkey


async def authentication_options(db: AsyncSession, user: User, purpose: ChallengePurpose) -> dict:
    options = generate_authentication_options(
        rp_id=rp_id(),
        challenge=await new_challenge(db, user.id, purpose),
        timeout=TIMEOUT_MS,
        allow_credentials=_descriptors(await list_passkeys(db, user.id)),
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return options_to_json_dict(options)


async def verify_assertion(
    db: AsyncSession, user: User, credential: dict, purpose: ChallengePurpose
) -> Passkey | None:
    """The person's passkey that signed this assertion, its counter and last use updated; None when it doesn't
    check out (the challenge is used up either way)."""
    challenge = await take_challenge(db, user.id, purpose)
    if challenge is None:
        return None
    try:
        parsed = parse_authentication_credential_json(credential)
        passkey = (
            await db.execute(
                select(Passkey).where(Passkey.user_id == user.id, Passkey.credential_id == parsed.raw_id)
            )
        ).scalar_one_or_none()
        if passkey is None:
            return None
        counter = parse_authenticator_data(parsed.response.authenticator_data).sign_count
        if (counter > 0 or passkey.sign_count > 0) and counter <= passkey.sign_count:
            # a counter that goes backwards: a cloned authenticator
            await audit.record(db, "auth.passkey_counter_rejected", target_type="user", target_id=user.id,
                               data={"name": passkey.name})
            return None
        verified = verify_authentication_response(
            credential=parsed, expected_challenge=challenge, expected_rp_id=rp_id(),
            expected_origin=expected_origin(), credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError):  # garbled JSON included: a failure, not a crash
        return None
    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = now()
    return passkey
