import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User, UserStatus


async def get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return user


async def active_admin_count(db: AsyncSession) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.role == Role.admin, User.status == UserStatus.active)
        )
    ).scalar_one()


async def ensure_not_last_admin(db: AsyncSession, user: User) -> None:
    if user.role == Role.admin and user.status == UserStatus.active and await active_admin_count(db) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "last_admin")
