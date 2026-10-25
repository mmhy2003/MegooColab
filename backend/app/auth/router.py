from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.audit import service as audit
from app.auth import service, totp
from app.auth.deps import CurrentUser, CurrentUserOrToken, current_session
from app.auth.models import Session, TokenPurpose, User, UserStatus
from app.auth.schemas import LowerEmail, Password, UserEnvelope, UserOut
from app.core.db import DbSession
from app.core.email import Mailer, get_mailer
from app.core.events import Event, publish
from app.core.security import DUMMY_HASH, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: LowerEmail
    password: str
    totp_code: str | None = None


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: DbSession) -> UserEnvelope:
    # row lock: parallel attempts must count one by one, or the lockout can be raced past
    user = (
        await db.execute(select(User).where(User.email == body.email).with_for_update())
    ).scalar_one_or_none()
    if user is None or user.password_hash is None:
        verify_password(body.password, DUMMY_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    if service.is_locked(user):
        raise HTTPException(status.HTTP_423_LOCKED, "locked")
    password_ok = verify_password(body.password, user.password_hash)
    if password_ok and user.status == UserStatus.active and user.totp_enabled and not body.totp_code:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "totp_required")
    totp_ok = not user.totp_enabled or totp.verify(user, body.totp_code)
    if not (password_ok and totp_ok) or user.status != UserStatus.active:
        locked = service.register_failed_login(user)
        await audit.record(db, "auth.login_failed", target_type="user", target_id=user.id)
        if locked:
            await audit.record(db, "auth.locked", target_type="user", target_id=user.id)
        # persist the counter and audit rows before the error rolls the request back
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    service.register_successful_login(user)
    token = await service.create_session(db, user, request.headers.get("user-agent"))
    await audit.record(db, "auth.login", actor_id=user.id)
    service.set_session_cookie(response, token)
    return UserEnvelope(user=UserOut.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response, db: DbSession, session: Annotated[Session, Depends(current_session)]
) -> None:
    await db.execute(delete(Session).where(Session.id == session.id))
    await publish(db, Event(type="sessions.revoked", user_id=session.user_id))
    service.clear_session_cookie(response)


@router.get("/me")
async def me(user: CurrentUserOrToken) -> UserEnvelope:
    return UserEnvelope(user=UserOut.model_validate(user))


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.patch("/me")
async def update_me(body: ProfileIn, user: CurrentUser) -> UserEnvelope:
    user.name = body.name
    return UserEnvelope(user=UserOut.model_validate(user))


class TokenPasswordIn(BaseModel):
    token: str
    password: Password


class ForgotIn(BaseModel):
    email: LowerEmail


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: Password


@router.post("/accept-invite")
async def accept_invite(
    body: TokenPasswordIn, request: Request, response: Response, db: DbSession
) -> UserEnvelope:
    user = await service.consume_token(db, body.token, TokenPurpose.invite)
    if user.status != UserStatus.invited:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_or_expired_token")
    user.password_hash = hash_password(body.password)
    user.status = UserStatus.active
    service.register_successful_login(user)
    token = await service.create_session(db, user, request.headers.get("user-agent"))
    await audit.record(db, "user.invite_accepted", actor_id=user.id)
    service.set_session_cookie(response, token)
    return UserEnvelope(user=UserOut.model_validate(user))


@router.post("/forgot", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    body: ForgotIn, db: DbSession, mailer: Annotated[Mailer | None, Depends(get_mailer)]
) -> None:
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None or user.status != UserStatus.active:
        return
    token = await service.issue_token(db, user, TokenPurpose.reset)
    url = service.token_url(TokenPurpose.reset, token)
    await service.try_send(
        mailer,
        user.email,
        "Reset your MegooColab password",
        f"Someone asked to reset your MegooColab password.\n\n{url}\n\n"
        "The link works once and expires in 1 hour. If it wasn't you, ignore this email.",
    )


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: TokenPasswordIn, db: DbSession) -> None:
    user = await service.consume_token(db, body.token, TokenPurpose.reset)
    if user.status != UserStatus.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_or_expired_token")
    user.password_hash = hash_password(body.password)
    user.must_change_password = False
    service.register_successful_login(user)
    await service.revoke_user_sessions(db, user.id)
    await audit.record(db, "auth.password_reset", actor_id=user.id)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordIn,
    user: CurrentUser,
    db: DbSession,
    session: Annotated[Session, Depends(current_session)],
) -> None:
    if user.password_hash is None or not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_current_password")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    await service.revoke_user_sessions(db, user.id, except_token_hash=session.token_hash)
    await audit.record(db, "auth.password_changed", actor_id=user.id)


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeIn(BaseModel):
    code: str


class TotpDisableIn(BaseModel):
    password: str
    code: str


@router.post("/totp/setup")
async def totp_setup(user: CurrentUser) -> TotpSetupOut:
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "totp_already_enabled")
    secret, uri = totp.start_setup(user)
    return TotpSetupOut(secret=secret, otpauth_uri=uri)


@router.post("/totp/enable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_enable(body: TotpCodeIn, user: CurrentUser, db: DbSession) -> None:
    if not totp.verify(user, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_code")
    user.totp_enabled = True
    await audit.record(db, "auth.totp_enabled", actor_id=user.id)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_disable(body: TotpDisableIn, user: CurrentUser, db: DbSession) -> None:
    password_ok = user.password_hash is not None and verify_password(body.password, user.password_hash)
    if not (password_ok and user.totp_enabled and totp.verify(user, body.code)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_password_or_code")
    user.totp_enabled = False
    user.totp_secret_enc = None
    await audit.record(db, "auth.totp_disabled", actor_id=user.id)
