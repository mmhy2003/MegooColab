"""The notification centre (NOT-1) and the signed-in user's preferences (NOT-2). Everyone sees only their own."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.audit import service as audit
from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.notifications.models import DEFAULT_PREFS, Kind, Notification, NotificationPref
from app.notifications.schemas import NotificationOut, NotificationPrefIO, UnreadCount

router = APIRouter(tags=["notifications"])

PAGE = 50


@router.get("/api/notifications")
async def list_notifications(user: AuthedUser, db: DbSession, unread: bool = False, before: datetime | None = None,
                             before_id: uuid.UUID | None = None) -> list[NotificationOut]:
    """Newest first, 50 per page; the next page starts before the last row's `created_at` (and `id`)."""
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    if before is not None:
        stmt = stmt.where(or_(Notification.created_at < before, and_(
            Notification.created_at == before, Notification.id < before_id)) if before_id else
            Notification.created_at < before)
    rows = (await db.execute(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(PAGE))
            ).scalars()
    return [NotificationOut.model_validate(n) for n in rows]


@router.get("/api/notifications/unread-count")
async def unread_count(user: AuthedUser, db: DbSession) -> UnreadCount:
    n = await db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)))
    return UnreadCount(count=n or 0)


@router.post("/api/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(notification_id: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    n = await db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification_not_found")
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(user: AuthedUser, db: DbSession) -> Response:
    await db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
                     .values(read_at=datetime.now(UTC)))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _prefs_out(db, user_id: uuid.UUID) -> list[NotificationPrefIO]:
    chosen = {p.kind: (p.in_app, p.email, p.push) for p in (await db.execute(
        select(NotificationPref).where(NotificationPref.user_id == user_id))).scalars()}
    return [NotificationPrefIO(kind=k, in_app=v[0], email=v[1], push=v[2])
            for k in Kind for v in [chosen.get(k, DEFAULT_PREFS[k])]]


@router.get("/api/me/notification-preferences")
async def get_preferences(user: AuthedUser, db: DbSession) -> list[NotificationPrefIO]:
    return await _prefs_out(db, user.id)


@router.put("/api/me/notification-preferences")
async def put_preferences(body: list[NotificationPrefIO], user: AuthedUser, db: DbSession) -> list[NotificationPrefIO]:
    """Kinds left out keep what they had."""
    for p in body:
        stmt = insert(NotificationPref).values(user_id=user.id, kind=p.kind, in_app=p.in_app, email=p.email,
                                               push=p.push)
        await db.execute(stmt.on_conflict_do_update(index_elements=["user_id", "kind"],
                                                    set_={"in_app": p.in_app, "email": p.email, "push": p.push}))
    if body:
        await audit.record(db, "notification.preferences_changed", actor_id=user.id, target_type="user",
                           target_id=user.id, data={p.kind.value: {"in_app": p.in_app, "email": p.email, "push": p.push} for p in body})
    await db.commit()
    return await _prefs_out(db, user.id)
