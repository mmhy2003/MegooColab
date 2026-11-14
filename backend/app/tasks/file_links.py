"""The files in a task's Attachments, as its agent gets them: listed, and downloaded through a short-lived link.

Images sent with a message belong to the run that message went to (app.images.delivery); only the files people put
in the task's Attachments section are listed here. A link names one file and when it stops working, signed with the
server's secret, so it downloads without signing in and can't be pointed at another file or kept alive longer."""

import hashlib
import hmac
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.config import get_settings
from app.tasks.models import Attachment, Task

LINK_LIFETIME = timedelta(minutes=15)
LINK_PATH = "/api/attachment-links"
PROMPT_LIMIT = 20  # files a run's prompt names; list_attachments lists them all


def task_files_where(task_id: uuid.UUID):
    return (Attachment.task_id == task_id, Attachment.message_kind.is_(None))


async def task_files(db: AsyncSession, task: Task) -> list[Attachment]:
    """The task's Attachments, oldest first."""
    rows = await db.execute(
        select(Attachment).where(*task_files_where(task.id)).order_by(Attachment.created_at, Attachment.id)
    )
    return list(rows.scalars())


async def task_file(db: AsyncSession, task: Task, attachment_id: uuid.UUID) -> Attachment | None:
    att = await db.get(Attachment, attachment_id)
    if att is None or att.task_id != task.id or att.message_kind is not None:
        return None
    return att


async def entries(db: AsyncSession, atts: Sequence[Attachment]) -> list[dict[str, Any]]:
    """How the agent's tools show each file."""
    names = {
        u.id: u.name
        for u in (await db.execute(select(User).where(User.id.in_({a.uploaded_by for a in atts if a.uploaded_by}))))
        .scalars()
    }
    return [
        {
            "id": str(a.id),
            "filename": a.filename,
            "content_type": a.content_type,
            "size": a.size,
            "image": a.image,
            "uploaded_by": names.get(a.uploaded_by) if a.uploaded_by else None,
            "created_at": a.created_at.isoformat(),
        }
        for a in atts
    ]


def _sig(attachment_id: uuid.UUID, expires: int) -> str:
    key = hashlib.sha256(b"attachment-link:" + get_settings().secret_key.encode()).digest()
    return hmac.new(key, f"{attachment_id}:{expires}".encode(), hashlib.sha256).hexdigest()


def signed_link(attachment_id: uuid.UUID, now: datetime | None = None) -> tuple[str, datetime]:
    """The file's download link, and when it stops working."""
    expires_at = (now or datetime.now(UTC)).replace(microsecond=0) + LINK_LIFETIME
    expires = int(expires_at.timestamp())
    base = get_settings().public_url.rstrip("/")
    return f"{base}{LINK_PATH}/{attachment_id}?expires={expires}&sig={_sig(attachment_id, expires)}", expires_at


def valid(attachment_id: uuid.UUID, expires: int, sig: str, now: datetime | None = None) -> bool:
    if (now or datetime.now(UTC)).timestamp() > expires:
        return False
    return hmac.compare_digest(sig.encode(), _sig(attachment_id, expires).encode())


def size_text(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def prompt_lines(atts: Sequence[Attachment]) -> list[str]:
    """The files a run's prompt names (at most PROMPT_LIMIT), and how many more there are."""
    lines = [f"- {a.filename} ({a.content_type}, {size_text(a.size)}, id {a.id})" for a in atts[:PROMPT_LIMIT]]
    if len(atts) > PROMPT_LIMIT:
        lines.append(f"({len(atts) - PROMPT_LIMIT} more: list_attachments lists them all)")
    return lines
