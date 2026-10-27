"""Who hears about what (NOT-1): `notify` writes a row per recipient, publishes it live and queues the email,
after dropping the actor, inactive users, recipients who cannot read the subject, and repeats."""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User, UserStatus
from app.core.email import get_mailer
from app.core.events import Event, publish
from app.jobs import queue
from app.notifications.models import DEFAULT_PREFS, Kind, Notification, NotificationPref
from app.projects.access import accessible_project_ids

DEDUPE_WINDOW = timedelta(minutes=10)


async def readable_by(db: AsyncSession, user: User, *, task_id: uuid.UUID | None = None,
                      project_id: uuid.UUID | None = None, question_id: uuid.UUID | None = None) -> bool:
    if user.status != UserStatus.active:
        return False
    if question_id is not None:
        # local: the a2a modules import the task modules, which import this one
        from app.a2a.access import can_read_question
        from app.a2a.models import Question

        q = await db.get(Question, question_id)
        if q is None or not await can_read_question(db, user, q):
            return False
    if task_id is not None:
        from app.tasks.models import Task

        project_id = await db.scalar(select(Task.project_id).where(Task.id == task_id))
        if project_id is None:
            return False
    if project_id is None:
        return True
    allowed = await accessible_project_ids(db, user)
    return allowed is None or project_id in allowed


async def preferences(db: AsyncSession, user_ids: Iterable[uuid.UUID], kind: Kind) -> dict[uuid.UUID, tuple[bool, bool]]:
    ids = list(user_ids)
    chosen = {p.user_id: (p.in_app, p.email) for p in (await db.execute(
        select(NotificationPref).where(NotificationPref.user_id.in_(ids), NotificationPref.kind == kind))).scalars()}
    return {uid: chosen.get(uid, DEFAULT_PREFS[kind]) for uid in ids}


async def _recent_unread(db: AsyncSession, user_ids: list[uuid.UUID], kind: Kind, task_id: uuid.UUID) -> set[uuid.UUID]:
    since = datetime.now(UTC) - DEDUPE_WINDOW
    return set((await db.execute(select(Notification.user_id).where(
        Notification.user_id.in_(user_ids), Notification.kind == kind, Notification.task_id == task_id,
        Notification.read_at.is_(None), Notification.created_at > since))).scalars())


async def notify(db: AsyncSession, user_ids: Iterable[uuid.UUID], kind: Kind, *, title: str, body: str, link: str,
                 task_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None,
                 actor_id: uuid.UUID | None = None) -> int:
    """Returns the number of in-app rows created. The caller commits; the email goes out after that commit."""
    ids = [uid for uid in dict.fromkeys(user_ids) if uid is not None and uid != actor_id]
    if not ids:
        return 0
    users = list((await db.execute(select(User).where(User.id.in_(ids)))).scalars())
    recipients = []
    for user in users:
        if kind == Kind.question_waiting and user.role == Role.viewer:
            continue  # a viewer cannot answer
        if await readable_by(db, user, task_id=task_id, project_id=project_id):
            recipients.append(user)
    if task_id is not None and recipients:
        repeats = await _recent_unread(db, [u.id for u in recipients], kind, task_id)
        recipients = [u for u in recipients if u.id not in repeats]
    if not recipients:
        return 0
    prefs = await preferences(db, [u.id for u in recipients], kind)
    title, body, link = title[:200], body[:500], link[:500]
    mail = await get_mailer(db) is not None
    created = 0
    for user in recipients:
        in_app, email = prefs[user.id]
        if in_app:
            db.add(Notification(user_id=user.id, kind=kind, title=title, body=body, link=link, task_id=task_id,
                                project_id=project_id))
            created += 1
            # user_id alone: an event with a project reaches every member of that project
            await publish(db, Event(type="notification.created", user_id=user.id))
        if email and mail:
            await queue.enqueue(db, "notify.email", {"user_id": str(user.id), "title": title, "body": body,
                                                     "link": link})
    await db.flush()
    return created
