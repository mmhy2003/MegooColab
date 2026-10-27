"""Worker jobs for pull-request tracking (GIT-3): a periodic poll of open pull requests, and a refresh of one
task's pull request (queued by a report, a webhook or the poll)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.git import service
from app.git.models import TaskPullRequest
from app.jobs import queue


@queue.register("git.pr_refresh")
async def pr_refresh(db: AsyncSession, payload: dict) -> None:
    row = await db.get(TaskPullRequest, uuid.UUID(str(payload["task_id"])))
    if row is not None and row.connection_id is not None:
        await service.refresh_pr(db, row)


@queue.register("git.pr_poll")
async def pr_poll(db: AsyncSession, payload: dict) -> None:
    """Open, tracked pull requests whose next check is due, oldest first: each in a transaction of its own, so
    one slow or failing provider does not hold the others back."""
    due = (
        await db.execute(
            select(TaskPullRequest.task_id)
            .where(TaskPullRequest.connection_id.is_not(None), TaskPullRequest.state == "open",
                   TaskPullRequest.next_check_at <= datetime.now(UTC))
            .order_by(TaskPullRequest.next_check_at, TaskPullRequest.task_id)
            .limit(service.POLL_LIMIT)
        )
    ).scalars().all()
    for task_id in due:
        async with SessionLocal() as s:
            row = await s.get(TaskPullRequest, task_id)
            if row is not None:
                await service.refresh_pr(s, row)
                await s.commit()


queue.register_periodic("git.pr_poll", service.POLL_SECONDS)
