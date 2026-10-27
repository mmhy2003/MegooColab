"""Worker jobs for notifications (NOT-2): the email for one notification. A send that raises fails the job, which
the queue retries; the action that caused it was committed long before."""

import uuid

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
