"""Worker jobs for pull-request tracking (GIT-3): a periodic poll of open pull requests, and a refresh of one
task's pull request (queued by a report, a webhook or the poll)."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.git import service
from app.git.models import TaskPullRequest
from app.jobs import queue

log = logging.getLogger(__name__)


@queue.register("git.pr_refresh")
async def pr_refresh(db: AsyncSession, payload: dict) -> None:
    row = await db.get(TaskPullRequest, uuid.UUID(str(payload["task_id"])))
    if row is not None and row.connection_id is not None:
        await service.refresh_pr(db, row)


# a connection failing like this fails for all its pull requests: try the rest at the next poll
_CONNECTION_DOWN = {"unreachable", "rate_limited", "unauthorized", "bad_token"}


@queue.register("git.pr_poll")
async def pr_poll(db: AsyncSession, payload: dict) -> None:
    """Open, tracked pull requests whose next check is due, oldest first: each in a transaction of its own, so
    one slow or failing provider, or one bad row, does not hold the others back."""
    due = (
        await db.execute(
            select(TaskPullRequest.task_id, TaskPullRequest.connection_id)
            .where(TaskPullRequest.connection_id.is_not(None), TaskPullRequest.state == "open",
                   TaskPullRequest.next_check_at <= datetime.now(UTC))
            .order_by(TaskPullRequest.next_check_at, TaskPullRequest.task_id)
            .limit(service.POLL_LIMIT)
        )
    ).all()
    down: set[uuid.UUID] = set()
    for task_id, connection_id in due:
        if connection_id in down:
            continue
        try:
            async with SessionLocal() as s:
                row = await s.get(TaskPullRequest, task_id)
                code = await service.refresh_pr(s, row) if row is not None else None
                await s.commit()
        except Exception:
            log.exception("pull request check failed for task %s", task_id)
            code = "error"
            async with SessionLocal() as s:
                await service.back_off(s, task_id, code)
                await s.commit()
        if code in _CONNECTION_DOWN:
            down.add(connection_id)


queue.register_periodic("git.pr_poll", service.POLL_SECONDS)
