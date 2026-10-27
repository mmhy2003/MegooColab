import uuid

import pytest

from app.core.config import get_settings
from app.search import client


@pytest.fixture
async def meili_index():
    """A fresh, uniquely named index with the app's settings; deleted afterwards."""
    settings = get_settings()
    before = settings.meili_index
    settings.meili_index = f"test_{uuid.uuid4().hex[:8]}"
    await client.ensure_index()
    try:
        yield settings.meili_index
    finally:
        try:
            await client.call(lambda: client.client().index(settings.meili_index).delete())
        finally:
            settings.meili_index = before


async def drain(rounds: int = 10, *, raise_errors: bool = True) -> int:
    """Run every queued search.* job now (ignoring backoff), as the worker would; returns how many ran. With
    `raise_errors=False` a failing job is recorded (and stays queued for retry) and draining stops."""
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.jobs import queue
    from app.jobs.models import Job, JobStatus
    from app.search import jobs  # noqa: F401 - registers the handlers

    ran = 0
    for _ in range(rounds):
        async with SessionLocal() as s:
            pending = (
                await s.execute(
                    select(Job.id, Job.kind, Job.payload)
                    .where(Job.status == JobStatus.queued, Job.kind.like("search.%"))
                    .order_by(Job.created_at)
                )
            ).all()
        if not pending:
            return ran
        for job_id, kind, payload in pending:
            ran += 1
            try:
                async with SessionLocal() as s:
                    await queue.HANDLERS[kind](s, dict(payload))
                    row = await s.get(Job, job_id, with_for_update=True)
                    await queue.complete(s, row)
                    await s.commit()
            except Exception as exc:
                async with SessionLocal() as s:
                    row = await s.get(Job, job_id, with_for_update=True)
                    await queue.fail(s, row, f"{type(exc).__name__}: {exc}")
                    await s.commit()
                if raise_errors:
                    raise
                return ran
    return ran
