"""Worker jobs for notifications (NOT-1, NOT-2): the email for one notification (a send that raises fails the
job, which the queue retries; the action that caused it was committed long before), and the periodic look for
agent-to-agent questions still queued after 15 minutes."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserStatus
from app.core.config import get_settings
from app.core.email import get_mailer, org_name
from app.core.email_template import Email, render
from app.jobs import queue


@queue.register("notify.email")
async def send_email(db: AsyncSession, payload: dict) -> None:
    user = await db.get(User, uuid.UUID(str(payload["user_id"])))
    mailer = await get_mailer(db)
    if user is None or user.status != UserStatus.active or mailer is None:
        return
    text, html = render(await _notification_email(db, payload), org=await org_name(db))
    await mailer.send(user.email, f"[MegooColab] {payload['title']}", text, html=html)


# each kind's tag, its colour, and why the person got it
KIND_LOOK: dict[str, tuple[str, str, str]] = {
    "needs_you": ("Needs you", "amber", "You get this because something you can act on waits for you."),
    "assigned": ("Assigned", "violet", "You get this because something was assigned to you."),
    "mentioned": ("Mentioned", "cyan", "You get this because someone mentioned you."),
    "agent_offline": ("Agent offline", "pink", "You get this because one of your agents went offline with work waiting."),
    "question_waiting": ("Question waiting", "amber", "You get this because a question waits for an answer."),
    "agent_replied": ("Agent replied", "green", "You get this because an agent replied in a chat you started."),
    "task_done": ("Done", "green", "You get this because a task assigned to you or your agent is done."),
    "team_task_done": ("Done", "green", "You get this because a task in one of your team's projects is done."),
}


def _button(link: str) -> str:
    if "task=" in link or "/tasks/" in link:
        return "Open the task"
    if link.startswith("/chats/"):
        return "Open the chat"
    if link.startswith("/questions/"):
        return "Open the question"
    return "Open in MegooColab"


async def _notification_email(db: AsyncSession, payload: dict) -> Email:
    from app.projects.models import Project  # local: projects import the notification service
    from app.tasks.models import Task

    public = get_settings().public_url
    tag, tone, why = KIND_LOOK.get(str(payload.get("kind") or ""), ("Notification", "cyan",
                                                                    "You get this from MegooColab."))
    key = None
    if payload.get("task_id"):
        task = await db.get(Task, uuid.UUID(str(payload["task_id"])))
        project = await db.get(Project, task.project_id) if task else None
        key = f"{project.key}-{task.number}" if project else None
    body = str(payload.get("body") or "")
    link = str(payload.get("link") or "")
    return Email(
        tag=tag, tone=tone, heading=str(payload["title"]),
        box=(key, body) if body or key else None,
        button=(_button(link), f"{public}{link}"),
        footer=why, footer_link=("Change which emails you get", f"{public}/settings/notifications"),
    )


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
