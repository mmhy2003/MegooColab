"""Deleted tasks' upload folders (`<upload root>/<task id>/`) are removed once the delete commits, never before: a
delete that fails or rolls back keeps its files."""

import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import get_settings

PENDING = "uploads_to_remove"


def remove_after_commit(db: AsyncSession, task_ids: Iterable[uuid.UUID]) -> None:
    root = Path(get_settings().upload_dir)
    db.sync_session.info.setdefault(PENDING, set()).update(root / str(task_id) for task_id in task_ids)


def _after_commit(session: Session) -> None:
    for folder in session.info.pop(PENDING, set()):
        shutil.rmtree(folder, ignore_errors=True)


def _after_soft_rollback(session: Session, _previous_transaction) -> None:
    session.info.pop(PENDING, None)


def install() -> None:
    """Register the hooks once, for every session."""
    if event.contains(Session, "after_commit", _after_commit):
        return
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_soft_rollback", _after_soft_rollback)


install()  # on import: every module that deletes tasks imports this one
