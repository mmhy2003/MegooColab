"""A project's crons: its managers set them up, its members read them and their runs."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.agents.service import can_use_agent, is_usable_binding
from app.audit import service as audit
from app.auth.models import User
from app.crons import schedule
from app.crons.models import Cron, CronRun
from app.crons.schemas import CronIn, CronOut, CronPatch, CronRunOut
from app.kb.schemas import Named
from app.projects.models import Project


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "cron_not_found")


def next_after(cron: Cron, now: datetime | None = None) -> datetime:
    return schedule.next_times(cron.schedule, cron.timezone, now or datetime.now(UTC), 1)[0]


async def _named(db: AsyncSession, model, id_: uuid.UUID | None) -> Named | None:
    row = await db.get(model, id_) if id_ else None
    return Named(id=row.id, name=row.name) if row else None


async def run_out(db: AsyncSession, run: CronRun) -> CronRunOut:
    from app.agent_runs.models import AgentRun  # local: agent_runs calls into the crons package

    agent_id = await db.scalar(select(AgentRun.agent_id).where(AgentRun.id == run.agent_run_id)) if run.agent_run_id else None
    return CronRunOut(
        id=run.id, scheduled_at=run.scheduled_at, status=run.status, skip_reason=run.skip_reason,
        agent=await _named(db, Agent, agent_id), started_at=run.started_at, finished_at=run.finished_at,
        report=run.report, commit=run.commit, tasks_created=run.tasks_created,
    )


async def cron_out(db: AsyncSession, cron: Cron) -> CronOut:
    project = await db.get(Project, cron.project_id)
    last = await db.scalar(
        select(CronRun).where(CronRun.cron_id == cron.id).order_by(CronRun.scheduled_at.desc()).limit(1)
    )
    return CronOut(
        id=cron.id, project_key=project.key, name=cron.name, prompt=cron.prompt, schedule=cron.schedule,
        timezone=cron.timezone, description=schedule.describe(cron.schedule), agent=await _named(db, Agent, cron.agent_id),
        mode=cron.mode, kb_title=cron.kb_title, kb_document_id=cron.kb_document_id,
        notify_findings=cron.notify_findings, notify_every=cron.notify_every, notify_failures=cron.notify_failures,
        paused=cron.paused, next_run_at=cron.next_run_at, last_run=await run_out(db, last) if last else None,
        created_by=await _named(db, User, cron.created_by), created_at=cron.created_at,
    )


async def get_cron(db: AsyncSession, project: Project, cron_id: uuid.UUID, *, lock: bool = False) -> Cron:
    stmt = select(Cron).where(Cron.id == cron_id, Cron.project_id == project.id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    cron = (await db.execute(stmt)).scalar_one_or_none()
    if cron is None:
        raise _not_found()
    return cron


async def _check_agent(db: AsyncSession, user: User, project: Project, agent_id: uuid.UUID | None) -> None:
    if agent_id is None:
        return
    agent = await db.get(Agent, agent_id)
    if (
        agent is None
        or not await is_usable_binding(db, agent.id, project.id)
        or not await can_use_agent(db, user, agent, project)
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_not_available")


def _audit_data(cron: Cron) -> dict:
    return {"name": cron.name, "project_id": str(cron.project_id)}


async def create(db: AsyncSession, user: User, project: Project, data: CronIn) -> Cron:
    schedule.check(data.schedule, data.timezone)
    await _check_agent(db, user, project, data.agent_id)
    cron = Cron(id=uuid.uuid4(), project_id=project.id, created_by=user.id, **data.model_dump())
    cron.next_run_at = next_after(cron)
    db.add(cron)
    await db.flush()
    await audit.record(db, "cron.created", actor_id=user.id, target_type="cron", target_id=cron.id,
                       data=_audit_data(cron))
    return cron


async def update(db: AsyncSession, user: User, project: Project, cron: Cron, data: CronPatch) -> Cron:
    changes = data.model_dump(exclude_unset=True)
    if "schedule" in changes or "timezone" in changes:
        schedule.check(changes.get("schedule", cron.schedule), changes.get("timezone", cron.timezone))
    if "agent_id" in changes:
        await _check_agent(db, user, project, changes["agent_id"])
    for key, value in changes.items():
        setattr(cron, key, value)
    if not cron.paused and ("schedule" in changes or "timezone" in changes):
        cron.next_run_at = next_after(cron)
    cron.updated_at = func.now()
    await db.flush()
    await audit.record(db, "cron.updated", actor_id=user.id, target_type="cron", target_id=cron.id,
                       data=_audit_data(cron))
    await db.refresh(cron)
    return cron


async def set_paused(db: AsyncSession, user: User, cron: Cron, paused: bool) -> Cron:
    cron.paused = paused
    cron.next_run_at = None if paused else next_after(cron)  # resuming never runs the times it missed
    await db.flush()
    await audit.record(db, "cron.paused" if paused else "cron.resumed", actor_id=user.id, target_type="cron",
                       target_id=cron.id, data=_audit_data(cron))
    return cron


async def delete(db: AsyncSession, user: User, cron: Cron) -> None:
    await audit.record(db, "cron.deleted", actor_id=user.id, target_type="cron", target_id=cron.id,
                       data=_audit_data(cron))
    await db.delete(cron)
    await db.flush()


async def runs(db: AsyncSession, cron: Cron, limit: int) -> list[CronRunOut]:
    rows = (
        await db.execute(
            select(CronRun).where(CronRun.cron_id == cron.id).order_by(CronRun.scheduled_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [await run_out(db, r) for r in rows]
