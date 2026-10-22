from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.audit import service as audit
from app.auth import service
from app.auth.deps import CurrentUser, current_session
from app.auth.models import Session, User, UserStatus
from app.auth.schemas import LowerEmail, UserEnvelope, UserOut
from app.core.db import DbSession
from app.core.security import DUMMY_HASH, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: LowerEmail
    password: str
    totp_code: str | None = None


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: DbSession) -> UserEnvelope:
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None or user.password_hash is None:
        verify_password(body.password, DUMMY_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    if service.is_locked(user):
        raise HTTPException(status.HTTP_423_LOCKED, "locked")
    if not verify_password(body.password, user.password_hash) or user.status != UserStatus.active:
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
    service.clear_session_cookie(response)


@router.get("/me")
async def me(user: CurrentUser) -> UserEnvelope:
    return UserEnvelope(user=UserOut.model_validate(user))
