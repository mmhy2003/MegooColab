"""The cron scheduler: every SCHEDULE_SECONDS it starts the crons that are due, each scheduled time exactly once (its
CronRun row is the claim), skips what can't run, and stops runs that wait or work too long."""

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunPolicy, RunStatus
from app.agents.models import Agent, AgentBinding
from app.agents.service import is_usable_binding, owner_can_access
from app.core.db import SessionLocal
from app.crons import service, turns
from app.crons.models import Cron, CronRun, CronRunStatus
from app.images.support import runner_has
from app.projects.models import Project, ProjectStatus
from app.runner.registry import CRONS_CAPABILITY, registry

log = logging.getLogger(__name__)

SCHEDULE_SECONDS = 30
CATCH_UP = timedelta(hours=1)  # a time missed for longer is skipped, never run late
AGENT_WAIT = timedelta(minutes=15)
TIME_LIMIT = timedelta(minutes=30)


async def _pick_agent(db: AsyncSession, cron: Cron) -> Agent | None:
    """The cron's chosen agent while it can still work on the project; else any agent of the project whose owner can
    still access it: one whose runner can run crons first, online first, then the least busy."""
    if not cron.any_agent:  # its chosen agent, or none at all (deleted): never another one
        agent = await db.get(Agent, cron.agent_id) if cron.agent_id else None
        ok = agent is not None and await is_usable_binding(db, agent.id, cron.project_id)
        return agent if ok else None
    agents = (
        await db.execute(
            select(Agent).join(AgentBinding, AgentBinding.agent_id == Agent.id)
            .where(AgentBinding.project_id == cron.project_id, owner_can_access(cron.project_id))
        )
    ).scalars().unique().all()
    if not agents:
        return None
    busy = dict((await db.execute(
        select(AgentRun.agent_id, func.count()).where(
            AgentRun.agent_id.in_([a.id for a in agents]), AgentRun.status.in_(ACTIVE_STATUSES)
        ).group_by(AgentRun.agent_id)
    )).all())
    ranked = []
    for a in agents:
        capable = await runner_has(db, a, CRONS_CAPABILITY)
        ranked.append((not capable, not registry.is_available(a.id), busy.get(a.id, 0), a.name.lower(), a))
    return min(ranked, key=lambda r: r[:4])[-1]


def _skip(run: CronRun, reason: str) -> None:
    run.status = CronRunStatus.skipped
    run.skip_reason = reason
    run.finished_at = datetime.now(UTC)


async def start_run(db: AsyncSession, cron: Cron, run: CronRun) -> None:
    """Starts a claimed scheduled time (or Run now) on one agent, or skips it with the reason."""
    still_going = await db.scalar(
        select(CronRun.id).where(CronRun.cron_id == cron.id, CronRun.id != run.id,
                                 CronRun.status.in_((CronRunStatus.queued, CronRunStatus.running))).limit(1)
    )
    if still_going is not None:
        _skip(run, "previous_running")
        await turns.tell_outcome(db, cron, run)
        return
    agent = await _pick_agent(db, cron)
    if agent is None:
        _skip(run, "no_agent")  # the managers are told whatever the cron's settings: it can't run until they act
        await turns.tell(db, cron, run, f"Cron {cron.name} skipped", turns.SKIP_TEXT["no_agent"])
        return
    prompt, version = await turns.cron_prompt(db, cron, run)
    agent_run = AgentRun(id=uuid.uuid4(), cron_run_id=run.id, agent_id=agent.id, requested_by=cron.created_by,
                         policy=RunPolicy.workspace, prompt=prompt, methodology_version_id=version.id)
    db.add(agent_run)
    await db.flush()
    run.agent_run_id = agent_run.id
    from app.workflow import engine  # local: the engine imports agent_runs, which calls into this package

    db.info.setdefault(engine._DISPATCH_KEY, set()).add(agent.owner_id)  # sent after the caller commits


async def run_now(db: AsyncSession, cron: Cron) -> CronRun:
    run = CronRun(id=uuid.uuid4(), cron_id=cron.id, scheduled_at=datetime.now(UTC), status=CronRunStatus.queued)
    db.add(run)
    await db.flush()
    await start_run(db, cron, run)
    return run


async def _claim(db: AsyncSession, cron_id: uuid.UUID, at: datetime, status: CronRunStatus,
                 reason: str | None = None) -> uuid.UUID | None:
    """The CronRun row of one scheduled time, if this call inserted it: the claim that makes the time run once."""
    return await db.scalar(
        insert(CronRun)
        .values(id=uuid.uuid4(), cron_id=cron_id, scheduled_at=at, status=status, skip_reason=reason,
                finished_at=datetime.now(UTC) if status == CronRunStatus.skipped else None)
        .on_conflict_do_nothing(constraint="cron_runs_cron_time_key")
        .returning(CronRun.id)
    )


async def _start_due(db: AsyncSession, now: datetime) -> None:
    crons = (
        await db.execute(
            select(Cron).where(Cron.paused.is_(False), Cron.next_run_at <= now)
            .with_for_update(of=Cron, skip_locked=True).execution_options(populate_existing=True)
        )
    ).scalars().all()
    for cron in crons:
        due = cron.next_run_at
        project = await db.get(Project, cron.project_id)
        if project.status != ProjectStatus.active:
            pass  # a finished or archived project's crons wait, unrun, until it is active again
        elif now - due > CATCH_UP:
            await _claim(db, cron.id, due, CronRunStatus.skipped, "missed")
        else:
            run_id = await _claim(db, cron.id, due, CronRunStatus.queued)
            if run_id is not None:
                await start_run(db, cron, await db.get(CronRun, run_id))
        cron.next_run_at = service.next_after(cron, now)


async def _end_waiting(db: AsyncSession, now: datetime) -> None:
    """Runs still queued AGENT_WAIT after their time: no agent could take them."""
    from app.agent_runs.service import cancel_waiting_run  # local: agent_runs calls into this package

    rows = (
        await db.execute(
            select(CronRun, AgentRun)
            .join(AgentRun, AgentRun.id == CronRun.agent_run_id)
            .where(CronRun.status.in_((CronRunStatus.queued, CronRunStatus.running)),
                   CronRun.claimed_at < now - AGENT_WAIT, AgentRun.status == RunStatus.queued)
            .with_for_update(of=CronRun, skip_locked=True)
        )
    ).all()
    for cron_run, agent_run in rows:
        cron_run.skip_reason = "no_agent_online"
        await cancel_waiting_run(db, agent_run, "no_agent_online")


async def _end_lost(db: AsyncSession, now: datetime) -> None:
    """Runs whose agent run is gone, or ended without ending them: they would block the cron for good."""
    rows = (
        await db.execute(
            select(CronRun).outerjoin(AgentRun, AgentRun.id == CronRun.agent_run_id)
            .where(CronRun.status.in_((CronRunStatus.queued, CronRunStatus.running)),
                   or_(CronRun.agent_run_id.is_(None), AgentRun.status.not_in(ACTIVE_STATUSES)))
            .with_for_update(of=CronRun, skip_locked=True)
        )
    ).scalars().all()
    for run in rows:
        run.status, run.skip_reason, run.finished_at = CronRunStatus.failed, "lost", now


async def _stop_overdue(db: AsyncSession, now: datetime) -> None:
    """Runs working longer than TIME_LIMIT are stopped; their report says so."""
    from app.agent_runs.service import stop_run  # local: agent_runs calls into this package

    rows = (
        await db.execute(
            select(CronRun, AgentRun)
            .join(AgentRun, AgentRun.id == CronRun.agent_run_id)
            .where(AgentRun.status == RunStatus.running, AgentRun.started_at < now - TIME_LIMIT,
                   CronRun.skip_reason.is_distinct_from("timed_out"))
            .with_for_update(of=CronRun, skip_locked=True)
        )
    ).all()
    for cron_run, agent_run in rows:
        cron_run.skip_reason = "timed_out"
        await stop_run(db, agent_run, "timed_out")


async def tick(now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    for step in (_start_due, _end_waiting, _end_lost, _stop_overdue):
        async with SessionLocal() as db:
            await step(db, now)
            from app.workflow import engine

            await db.commit()
            await engine.dispatch_queued(db)


async def cron_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await tick()
        except Exception:
            log.exception("cron scheduling failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), SCHEDULE_SECONDS)
