"""PostgreSQL-backed job queue: enqueue inside the caller's transaction, claim with SKIP LOCKED.

A job is claimed with a lease; a worker that dies leaves the lease to expire and the job is claimed
again. Handlers must therefore be idempotent.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import Job, JobStatus

CHANNEL = "megoo_jobs"
LEASE = timedelta(minutes=5)
MAX_BACKOFF = timedelta(hours=1)
ERROR_LIMIT = 500

Handler = Callable[[AsyncSession, dict], Awaitable[None]]
HANDLERS: dict[str, Handler] = {}
# kind -> seconds: the worker enqueues these jobs (deduplicated) every interval
PERIODIC: dict[str, float] = {}


def register(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


def register_periodic(kind: str, seconds: float) -> None:
    PERIODIC[kind] = seconds


def backoff(attempts: int) -> timedelta:
    return min(timedelta(seconds=10 * 2 ** min(attempts, 20)), MAX_BACKOFF)


async def enqueue(
    db: AsyncSession,
    kind: str,
    payload: dict[str, Any],
    *,
    dedupe_key: str | None = None,
    run_after: datetime | Any | None = None,
) -> Job | None:
    """Returns None when a queued job with the same dedupe key already exists. Workers are woken on commit."""
    values: dict[str, Any] = {"kind": kind, "payload": payload, "dedupe_key": dedupe_key}
    if run_after is not None:
        values["run_after"] = run_after
    stmt = (
        insert(Job)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["dedupe_key"], index_where=text("status = 'queued'"))
        .returning(Job.id)
    )
    job_id = (await db.execute(stmt)).scalar_one_or_none()
    if job_id is None:
        return None
    await db.execute(text("SELECT pg_notify(:c, :k)"), {"c": CHANNEL, "k": kind})
    return await db.get(Job, job_id)


async def claim(db: AsyncSession, kinds: set[str]) -> Job | None:
    """Takes the oldest due job of the given kinds, or a running one whose lease expired. The caller commits."""
    if not kinds:
        return None
    while True:
        job = (
            await db.execute(
                select(Job)
                .where(
                    Job.kind.in_(kinds),
                    or_(
                        and_(Job.status == JobStatus.queued, Job.run_after <= func.now()),
                        and_(Job.status == JobStatus.running, Job.locked_until < func.now()),
                    ),
                )
                .order_by(Job.run_after, Job.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if job is None:
            return None
        if job.status == JobStatus.running and job.attempts >= job.max_attempts:
            # the worker died on its last attempt
            job.status = JobStatus.failed
            job.last_error = "lease_expired"
            job.locked_until = None
            job.finished_at = func.now()
            await db.flush()
            continue
        job.status = JobStatus.running
        job.attempts += 1
        job.locked_until = func.now() + LEASE
        await db.flush()
        await db.refresh(job)
        return job


async def complete(db: AsyncSession, job: Job) -> None:
    job.status = JobStatus.done
    job.locked_until = None
    job.finished_at = func.now()
    await db.flush()


async def fail(db: AsyncSession, job: Job, error: str) -> None:
    """Re-queues with backoff while attempts remain, otherwise marks the job failed."""
    job.last_error = error[:ERROR_LIMIT]
    job.locked_until = None
    newer = job.dedupe_key is not None and await db.scalar(
        select(Job.id).where(Job.dedupe_key == job.dedupe_key, Job.status == JobStatus.queued, Job.id != job.id)
    )
    if newer:
        # a newer copy is queued (dedupe keeps one): it does this work again, so this attempt ends here
        job.status = JobStatus.failed
        job.last_error = f"{error} (a newer queued job replaces this one)"[:ERROR_LIMIT]
        job.finished_at = func.now()
    elif job.attempts < job.max_attempts:
        job.status = JobStatus.queued
        job.run_after = func.now() + backoff(job.attempts)
    else:
        job.status = JobStatus.failed
        job.finished_at = func.now()
    await db.flush()
