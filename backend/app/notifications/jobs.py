"""Worker jobs for notifications (NOT-1, NOT-2): the email for one notification (a send that raises fails the
job, which the queue retries; the action that caused it was committed long before), and the periodic look for
agent-to-agent questions still queued after 15 minutes."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserStatus
from app.core.config import get_settings
from app.core.email import get_mailer
from app.jobs import queue


@queue.register("notify.email")
async def send_email(db: AsyncSession, payload: dict) -> None:
    user = await db.get(User, uuid.UUID(str(payload["user_id"])))
    mailer = await get_mailer(db)
    if user is None or user.status != UserStatus.active or mailer is None:
        return
    await mailer.send(user.email, f"[MegooColab] {payload['title']}",
                      f"{payload['body']}\n\n{get_settings().public_url}{payload['link']}")


WAITING_AFTER = timedelta(minutes=15)
WAITING_TICK_SECONDS = 300
WAITING_LIMIT = 100


@queue.register("notify.questions_waiting")
async def questions_waiting(db: AsyncSession, payload: dict) -> None:
    # local: the a2a modules import the task modules, which import the notification service
    from app.a2a.models import Question, QuestionStatus
    from app.a2a.service import notify_waiting

    due = (Question.status == QuestionStatus.queued, Question.waiting_notified_at.is_(None),
           Question.created_at < datetime.now(UTC) - WAITING_AFTER)
    ids = (await db.execute(select(Question.id).where(*due).order_by(Question.created_at).limit(WAITING_LIMIT)
                            )).scalars().all()
    for qid in ids:
        q = (await db.execute(select(Question).where(Question.id == qid, *due).with_for_update(skip_locked=True)
                              .execution_options(populate_existing=True))).scalar_one_or_none()
        if q is not None:
            await notify_waiting(db, q)


queue.register_periodic("notify.questions_waiting", WAITING_TICK_SECONDS)
