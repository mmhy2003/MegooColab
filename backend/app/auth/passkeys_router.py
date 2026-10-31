from fastapi import APIRouter, HTTPException, status

from app.auth import passkeys
from app.auth.deps import CurrentUser
from app.auth.schemas import PasskeyCreateIn, PasskeyOut
from app.core.db import DbSession

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
