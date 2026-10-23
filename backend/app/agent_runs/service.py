import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunPolicy, RunStatus
from app.agent_runs.schemas import RunAgentOut, RunOut
from app.agents.models import Agent, AgentBinding
from app.agents.service import can_use_agent, publish_agents_updated
from app.auth.models import User
from app.core.events import Event, publish
from app.projects.models import Project
from app.runner.protocol import RunCancel, RunStart, RunTask
from app.runner.registry import RunnerClosed, RunnerConn, registry
from app.tasks.models import Task
from app.tasks.service import record_event

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def default_prompt(task_key: str, task: Task) -> str:
    return f"Work on task {task_key}: {task.title}\n\n{task.description_md}"


async def _announce(db: AsyncSession, task: Task, owner_id: uuid.UUID) -> None:
    """A run's status changed: refresh the task and the project's agent views."""
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
    await publish_agents_updated(db, owner_id, {task.project_id})


async def _transition(
    db: AsyncSession,
    run: AgentRun,
    to: RunStatus,
    event_kind: str,
    *,
    owner_id: uuid.UUID,
    reason: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Move a run to a terminal status, record it on the task and tell the browsers."""
    run.status = to
    run.reason = reason
    run.finished_at = _now()
    task = await db.get(Task, run.task_id)
    data = {"run_id": str(run.id)}
    if reason:
        data["reason"] = reason
    await record_event(db, task, actor_id, event_kind, data)
    await _announce(db, task, owner_id)


async def start_run(
    db: AsyncSession, user: User, task: Task, project: Project, policy: RunPolicy, prompt: str | None
) -> AgentRun:
    if task.assignee_agent_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "task_not_assigned_to_agent")
    agent = await db.get(Agent, task.assignee_agent_id)
    if agent is None or not await can_use_agent(db, user, agent, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot_use_agent")
    bound = await db.scalar(
        select(AgentBinding.id).where(AgentBinding.agent_id == agent.id, AgentBinding.project_id == project.id)
    )
    if bound is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_not_bound")
    text = (prompt or "").strip() or default_prompt(f"{project.key}-{task.number}", task)
    run = AgentRun(
        task_id=task.id, agent_id=agent.id, requested_by=user.id, policy=policy,
        prompt=text, status=RunStatus.queued,
    )
    db.add(run)
    await db.flush()
    await record_event(db, task, user.id, "agent_run_queued", {"run_id": str(run.id), "policy": policy})
    await _announce(db, task, agent.owner_id)
    await dispatch_pending(db, agent.owner_id)
    await db.refresh(run)  # server defaults (created_at) and any dispatch changes
    return run


async def _start_one(db: AsyncSession, conn: RunnerConn, agent: Agent, run: AgentRun) -> bool:
    """Mark one locked queued run running and send run_start. False if the connection is gone
    (the run is back to queued in this same transaction)."""
    row = (
        await db.execute(
            select(Task, Project.key, AgentBinding.local_path)
            .join(Project, Project.id == Task.project_id)
            .outerjoin(
                AgentBinding,
                (AgentBinding.project_id == Task.project_id) & (AgentBinding.agent_id == agent.id),
            )
            .where(Task.id == run.task_id)
        )
    ).one()
    task, project_key, local_path = row
    if local_path is None:  # the binding was removed while the run waited
        await _transition(db, run, RunStatus.failed, "agent_run_failed", owner_id=agent.owner_id, reason="agent_not_bound")
        return True
    run.status = RunStatus.running
    run.started_at = _now()
    await db.flush()
    try:
        await conn.send(
            RunStart(
                run_id=run.id,
                agent_id=agent.id,
                task=RunTask(
                    key=f"{project_key}-{task.number}",
                    title=task.title,
                    description_md=task.description_md,
                    project_key=project_key,
                ),
                local_path=local_path,
                policy=run.policy,
                prompt=run.prompt,
            )
        )
    except RunnerClosed:
        run.status = RunStatus.queued
        run.started_at = None
        await db.flush()
        return False
    conn.run_ids.add(run.id)
    await record_event(db, task, None, "agent_run_started", {"run_id": str(run.id)})
    await _announce(db, task, agent.owner_id)
    return True


async def dispatch_pending(db: AsyncSession, owner_id: uuid.UUID) -> None:
    """Send run_start for each available agent's oldest queued runs, up to its free slots.

    The agent row is locked first (FOR NO KEY UPDATE, held to the end of the caller's transaction) so
    concurrent dispatches for one agent are serialised and cannot overshoot max_concurrent_runs; the run
    rows are then locked with SKIP LOCKED and marked running before run_start goes out.
    """
    conn = registry.conn_for_user(owner_id)
    if conn is None:
        return
    for agent_id in sorted(conn.available):
        agent = (
            await db.execute(
                select(Agent)
                .where(Agent.id == agent_id, Agent.owner_id == owner_id)
                .with_for_update(key_share=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if agent is None:
            continue
        running = await db.scalar(
            select(func.count()).select_from(AgentRun).where(
                AgentRun.agent_id == agent.id, AgentRun.status == RunStatus.running
            )
        )
        free = agent.max_concurrent_runs - (running or 0)
        if free <= 0:
            continue
        queued = (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.agent_id == agent.id, AgentRun.status == RunStatus.queued)
                .order_by(AgentRun.created_at, AgentRun.id)
                .limit(free)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
        for run in queued:
            if not await _start_one(db, conn, agent, run):
                return  # the connection died: everything stays queued


async def _lock_run(db: AsyncSession, run_id: uuid.UUID) -> AgentRun | None:
    return (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def cancel_run(db: AsyncSession, user: User, run: AgentRun) -> None:
    """Queued: cancelled now. Running with a live runner: run_cancel is sent and the run is closed when its
    run_finished arrives. Running with the runner gone: cancelled now."""
    agent = await db.get(Agent, run.agent_id)
    task = await db.get(Task, run.task_id)
    project = await db.get(Project, task.project_id)
    if not await can_use_agent(db, user, agent, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot_use_agent")
    run = await _lock_run(db, run.id)
    if run.status not in ACTIVE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "run_not_active")
    if run.status == RunStatus.running:
        conn = registry.conn_for_user(agent.owner_id)
        if conn is not None and run.id in conn.run_ids:
            try:
                await conn.send(RunCancel(run_id=run.id))
                return
            except RunnerClosed:
                pass
    await _transition(
        db, run, RunStatus.cancelled, "agent_run_cancelled", owner_id=agent.owner_id, actor_id=user.id
    )


async def fail_disconnected_runs(db: AsyncSession, conn: RunnerConn) -> None:
    """The runner is gone: its running runs fail with runner_disconnected. If a newer connection already
    took over, only the runs this connection was given are failed."""
    stmt = (
        select(AgentRun, Agent.owner_id)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(Agent.owner_id == conn.user_id, AgentRun.status == RunStatus.running)
        .with_for_update(of=AgentRun)
        .execution_options(populate_existing=True)
    )
    superseded = registry.conn_for_user(conn.user_id) is not None
    for run, owner_id in (await db.execute(stmt)).all():
        if superseded and run.id not in conn.run_ids:
            continue
        await _transition(
            db, run, RunStatus.failed, "agent_run_failed", owner_id=owner_id, reason="runner_disconnected"
        )


async def cancel_user_runs(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Deactivation: cancel the user's queued and running runs, on their agents or requested by them.
    Running ones get a best-effort run_cancel on the agent owner's connection."""
    stmt = (
        select(AgentRun, Agent.owner_id)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(
            AgentRun.status.in_(ACTIVE_STATUSES),
            (Agent.owner_id == user_id) | (AgentRun.requested_by == user_id),
        )
        .order_by(AgentRun.created_at)
        .with_for_update(of=AgentRun)
        .execution_options(populate_existing=True)
    )
    for run, owner_id in (await db.execute(stmt)).all():
        if run.status == RunStatus.running:
            conn = registry.conn_for_user(owner_id)
            if conn is not None:
                try:
                    await conn.send(RunCancel(run_id=run.id))
                except RunnerClosed:
                    pass
        await _transition(db, run, RunStatus.cancelled, "agent_run_cancelled", owner_id=owner_id, reason="user_deactivated")


async def runs_out(db: AsyncSession, runs: list[AgentRun]) -> list[RunOut]:
    if not runs:
        return []
    agents = {
        a.id: a
        for a in (await db.execute(select(Agent).where(Agent.id.in_({r.agent_id for r in runs})))).scalars()
    }
    keys = {
        t_id: f"{pkey}-{num}"
        for t_id, pkey, num in await db.execute(
            select(Task.id, Project.key, Task.number)
            .join(Project, Project.id == Task.project_id)
            .where(Task.id.in_({r.task_id for r in runs}))
        )
    }
    return [
        RunOut(
            id=r.id,
            task_key=keys[r.task_id],
            agent=RunAgentOut(id=r.agent_id, name=agents[r.agent_id].name, program=agents[r.agent_id].program),
            policy=r.policy,
            status=r.status,
            reason=r.reason,
            summary=r.summary,
            created_at=r.created_at,
            started_at=r.started_at,
            finished_at=r.finished_at,
        )
        for r in runs
    ]
