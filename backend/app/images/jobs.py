"""Unsent images (uploaded for a message that was never sent) are removed after a day."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.jobs import queue
from app.tasks.models import Attachment

UNSENT_FOR = timedelta(days=1)
CLEANUP_SECONDS = 3600


async def cleanup_unsent(db: AsyncSession) -> None:
    rows = (
        await db.execute(
            select(Attachment).where(Attachment.task_id.is_(None), Attachment.created_at < datetime.now(UTC) - UNSENT_FOR)
        )
    ).scalars()
    root = Path(get_settings().upload_dir)
    for att in rows:
        (root / att.storage_key).unlink(missing_ok=True)
        await db.delete(att)


@queue.register("images.cleanup")
async def _cleanup(db: AsyncSession, _payload: dict) -> None:
    await cleanup_unsent(db)


queue.register_periodic("images.cleanup", CLEANUP_SECONDS)
