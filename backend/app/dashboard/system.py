"""System status for admins: runners, the job queue, search, AI, memory and rate limits. The search line asks the
search engine over HTTP, so its answer is kept for 60 seconds."""

import time
from datetime import UTC, datetime, timedelta, tzinfo

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.ai.models import AiProvider, AiUsage
from app.audit.models import AuditLog
from app.dashboard.schemas import SystemOut
from app.dashboard.scope import day_start, today
from app.jobs.models import Job, JobStatus
from app.memory.models import MemDreamRun
from app.runner.registry import registry
from app.search import client as search_client

SEARCH_CACHE_SECONDS = 60
_search_cache: tuple[float, bool, int | None] | None = None


def reset_search_cache() -> None:
    global _search_cache
    _search_cache = None


async def _search() -> tuple[bool, int | None]:
    """(available, indexed documents), as the Search admin page computes them."""
    global _search_cache
    if _search_cache is not None and time.monotonic() - _search_cache[0] < SEARCH_CACHE_SECONDS:
        return _search_cache[1], _search_cache[2]
    available, documents = await search_client.health(), None
    if available:
        try:
            documents = await search_client.document_count()
        except search_client.SearchUnavailable:
            available = False
    _search_cache = (time.monotonic(), available, documents)
    return available, documents


async def system(db: AsyncSession, tz: tzinfo | None = None) -> SystemOut:
    now, since_midnight = datetime.now(UTC), day_start(today(tz), tz)
    ready = (Job.status == JobStatus.queued, Job.run_after <= func.now())
    row = (await db.execute(select(
        exists(select(Agent.id)).label("agents_exist"),
        select(func.count()).select_from(Job).where(*ready).scalar_subquery().label("jobs_waiting"),
        select(func.min(Job.run_after)).where(*ready).scalar_subquery().label("oldest_job"),
        exists(select(AiProvider.id)).label("ai_configured"),
        select(func.count()).select_from(AiUsage).where(AiUsage.created_at >= since_midnight)
        .scalar_subquery().label("ai_jobs_today"),
        select(func.count()).select_from(AiUsage).where(AiUsage.created_at >= since_midnight, AiUsage.ok.is_(False))
        .scalar_subquery().label("ai_failed_today"),
        select(func.count()).select_from(AuditLog)
        .where(AuditLog.action == "rate_limit.blocked", AuditLog.created_at >= now - timedelta(hours=24))
        .scalar_subquery().label("rate_limits_24h"),
    ))).one()
    memory = (await db.execute(
        select(MemDreamRun.finished_at, MemDreamRun.status).where(MemDreamRun.finished_at.is_not(None))
        .order_by(MemDreamRun.finished_at.desc()).limit(1)
    )).first()
    available, documents = await _search()
    return SystemOut(
        runners=registry.connected_count(), agents_exist=row.agents_exist,
        jobs_waiting=row.jobs_waiting,
        oldest_job_seconds=max(0, int((now - row.oldest_job).total_seconds())) if row.oldest_job else None,
        search_available=available, search_documents=documents,
        ai_configured=row.ai_configured, ai_jobs_today=row.ai_jobs_today, ai_failed_today=row.ai_failed_today,
        memory_last_at=memory.finished_at if memory else None,
        memory_last_failed=bool(memory and memory.status == "failed"),
        rate_limits_24h=row.rate_limits_24h,
    )
