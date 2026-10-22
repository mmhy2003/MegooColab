import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth import service as auth_service
from app.auth.deps import AdminUser
from app.auth.models import TokenPurpose, User, UserStatus
from app.auth.schemas import UserEnvelope, UserOut
from app.core.db import DbSession
from app.core.email import Mailer, get_mailer
from app.core.security import hash_password
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.users.schemas import CreateUserIn, InviteIn, InviteOut, ResetLinkOut

admin_router = APIRouter(prefix="/api/admin/users", tags=["admin"])


async def _ensure_email_free(db: AsyncSession, email: str) -> None:
    if (await db.execute(select(User.id).where(User.email == email))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "email_taken")


async def _org_name(db: AsyncSession) -> str:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    return org.name if org else "MegooColab"


@admin_router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteIn,
    admin: AdminUser,
    db: DbSession,
    mailer: Annotated[Mailer | None, Depends(get_mailer)],
) -> InviteOut:
    await _ensure_email_free(db, body.email)
    user = User(email=body.email, name=body.name, role=body.role, status=UserStatus.invited)
    db.add(user)
    await db.flush()
    token = await auth_service.issue_token(db, user, TokenPurpose.invite)
    url = auth_service.token_url(TokenPurpose.invite, token)
    org = await _org_name(db)
    sent = await auth_service.try_send(
        mailer,
        user.email,
        f"You're invited to {org} on MegooColab",
        f"{admin.name} invited you to join {org} on MegooColab.\n\n{url}\n\n"
        "The link works once and expires in 7 days.",
    )
    await audit.record(
        db, "user.invited", actor_id=admin.id, target_type="user", target_id=user.id,
        data={"email": user.email, "role": user.role},
    )
    return InviteOut(user=UserOut.model_validate(user), invite_url=url, email_sent=sent)


@admin_router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(body: CreateUserIn, admin: AdminUser, db: DbSession) -> UserEnvelope:
    await _ensure_email_free(db, body.email)
    user = User(
        email=body.email,
        name=body.name,
        role=body.role,
        status=UserStatus.active,
        password_hash=hash_password(body.temporary_password),
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    await audit.record(
        db, "user.created", actor_id=admin.id, target_type="user", target_id=user.id,
        data={"email": user.email, "role": user.role},
    )
    return UserEnvelope(user=UserOut.model_validate(user))


@admin_router.post("/{user_id}/reset-link", status_code=status.HTTP_201_CREATED)
async def reset_link(user_id: uuid.UUID, admin: AdminUser, db: DbSession) -> ResetLinkOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    # an invited user who lost their invite gets a fresh invite link instead
    purpose = TokenPurpose.invite if user.status == UserStatus.invited else TokenPurpose.reset
    token = await auth_service.issue_token(db, user, purpose)
    await audit.record(
        db, "user.reset_link_created", actor_id=admin.id, target_type="user", target_id=user.id
    )
    return ResetLinkOut(reset_url=auth_service.token_url(purpose, token))
