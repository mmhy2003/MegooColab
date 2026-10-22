import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth import service as auth_service
from app.auth.deps import AdminUser, AuthedUser
from app.auth.models import Role, TokenPurpose, User, UserStatus
from app.auth.schemas import UserEnvelope, UserOut
from app.core.db import DbSession
from app.core.email import Mailer, get_mailer
from app.core.events import Event, publish
from app.core.security import hash_password
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.users import service as users_service
from app.users.schemas import CreateUserIn, InviteIn, InviteOut, ResetLinkOut, UpdateUserIn

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


@admin_router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID, body: UpdateUserIn, admin: AdminUser, db: DbSession
) -> UserEnvelope:
    user = await users_service.get_user_or_404(db, user_id)
    if body.name is not None:
        user.name = body.name
    if body.role is not None and body.role != user.role:
        if user.role == Role.admin:
            await users_service.ensure_not_last_admin(db, user)
        await audit.record(
            db, "user.role_changed", actor_id=admin.id, target_type="user", target_id=user.id,
            data={"from": user.role, "to": body.role},
        )
        user.role = body.role
        # access is role-dependent (admins see every project): open sockets must recompute it
        await publish(db, Event(type="membership.changed", user_id=user.id))
    return UserEnvelope(user=UserOut.model_validate(user))


@admin_router.post("/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(user_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    user = await users_service.get_user_or_404(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot_deactivate_self")
    await users_service.ensure_not_last_admin(db, user)
    user.status = UserStatus.deactivated
    await auth_service.revoke_user_sessions(db, user.id)
    await audit.record(db, "user.deactivated", actor_id=admin.id, target_type="user", target_id=user.id)
    await publish(db, Event(type="user.deactivated", user_id=user.id))


@admin_router.post("/{user_id}/reactivate", status_code=status.HTTP_204_NO_CONTENT)
async def reactivate_user(user_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    user = await users_service.get_user_or_404(db, user_id)
    if user.status != UserStatus.deactivated:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_deactivated")
    # an account that never accepted its invite goes back to invited
    user.status = UserStatus.active if user.password_hash else UserStatus.invited
    await audit.record(db, "user.reactivated", actor_id=admin.id, target_type="user", target_id=user.id)


users_router = APIRouter(prefix="/api/users", tags=["users"])


@users_router.get("")
async def list_users(
    user: AuthedUser,
    db: DbSession,
    q: str | None = None,
    status_: Annotated[UserStatus | None, Query(alias="status")] = None,
) -> list[UserOut]:
    stmt = select(User).order_by(User.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.email.ilike(like)))
    if status_:
        stmt = stmt.where(User.status == status_)
    return [UserOut.model_validate(u) for u in (await db.execute(stmt)).scalars()]
