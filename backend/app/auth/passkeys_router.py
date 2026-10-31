import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.audit import service as audit
from app.auth import passkeys, totp
from app.auth.deps import CurrentUser
from app.auth.models import ChallengePurpose, Passkey, User
from app.auth.schemas import PasskeyCreateIn, PasskeyOut, PasskeyRemoveIn
from app.core.db import DbSession
from app.core.security import verify_password
from app.ratelimit import guards

router = APIRouter(prefix="/api/auth/passkeys", tags=["auth"])

_STATUS = {"too_many_passkeys": status.HTTP_409_CONFLICT, "passkey_exists": status.HTTP_409_CONFLICT}


def _http(err: passkeys.PasskeyError) -> HTTPException:
    return HTTPException(_STATUS.get(err.code, status.HTTP_400_BAD_REQUEST), err.code)


@router.get("")
async def list_passkeys(user: CurrentUser, db: DbSession) -> list[PasskeyOut]:
    return [PasskeyOut.model_validate(p) for p in await passkeys.list_passkeys(db, user.id)]


@router.post("/options")
async def registration_options(user: CurrentUser, db: DbSession) -> dict:
    try:
        return await passkeys.registration_options(db, user)
    except passkeys.PasskeyError as err:
        raise _http(err) from err


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_passkey(body: PasskeyCreateIn, user: CurrentUser, db: DbSession) -> PasskeyOut:
    try:
        passkey = await passkeys.register(db, user, body.name, body.credential)
    except passkeys.PasskeyError as err:
        # the challenge is used up whatever the answer: keep that, and only that
        await db.commit()
        raise _http(err) from err
    return PasskeyOut.model_validate(passkey)


async def _own_passkey(db, user: User, passkey_id: uuid.UUID) -> Passkey:
    passkey = (
        await db.execute(select(Passkey).where(Passkey.id == passkey_id, Passkey.user_id == user.id))
    ).scalar_one_or_none()
    if passkey is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return passkey


@router.post("/{passkey_id}/remove-options")
async def remove_options(passkey_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    """For the removal dialog's passkey prompt: any of the person's passkeys confirms it."""
    await _own_passkey(db, user, passkey_id)
    return await passkeys.authentication_options(db, user, ChallengePurpose.remove)


@router.delete("/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_passkey(
    passkey_id: uuid.UUID, body: PasskeyRemoveIn, request: Request, user: CurrentUser, db: DbSession
) -> None:
    """The password and a second factor (a passkey or the authenticator code), as turning off the app asks: so
    removing the last passkey never turns two-factor sign-in off with only a session and a password."""
    passkey = await _own_passkey(db, user, passkey_id)
    await guards.check("totp_account", str(user.id), request, actor_id=user.id)
    password_ok = user.password_hash is not None and verify_password(body.password, user.password_hash)
    if body.passkey:
        factor_ok = await passkeys.verify_assertion(db, user, body.passkey, ChallengePurpose.remove) is not None
    else:
        factor_ok = user.totp_enabled and totp.verify(user, body.totp_code)
    if not (password_ok and factor_ok):
        if password_ok:  # a wrong second factor counts only behind the right password
            await guards.count("totp_account", str(user.id))
        await db.commit()  # a used challenge stays used
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_password_or_code")
    name = passkey.name
    await db.delete(passkey)
    await audit.record(db, "auth.passkey_removed", actor_id=user.id, target_type="user", target_id=user.id,
                       data={"name": name})
