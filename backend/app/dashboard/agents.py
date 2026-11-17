"""Agents and their runs: who is working, idle or offline, what is running and queued, and failed runs. A run is in
scope through its project: its task's, the question's target project (a run answering another project's question),
or its cron's."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun, RunStatus
from app.agent_runs.running import run_project_id, run_targets, running_items
from app.agents.models import Agent, AgentBinding
from app.agents.service import agent_statuses, runner_info
from app.dashboard.schemas import AgentItem, Queued, QueuedItem, RunningItem
from app.dashboard.scope import Scope, task_link
from app.projects.models import Project
from app.tasks.models import Task

QUEUED_SHOWN = 5
_ORDER = {"busy": 0, "busy_elsewhere": 1, "online": 2, "offline": 3}


def _in_scope(scope: Scope) -> ColumnElement[bool]:
    """Runs in scope, over run_targets: through their project (a task's, a question's target or a cron's)."""
    # a Knowledge Base draft's turns are its person's own: not on anyone's dashboard
    cond = and_(AgentRun.draft_id.is_(None), scope.in_projects(run_project_id()))
    return and_(cond, AgentRun.agent_id.in_(scope.agent_ids)) if scope.name == "mine" else cond


def _runs(scope: Scope, *columns):
    """A select over runs in scope, with the run's task, question and cron joined."""
    return run_targets(*columns).where(_in_scope(scope))


async def agents(db: AsyncSession, scope: Scope) -> list[AgentItem]:
    stmt = select(Agent.id, Agent.name, Agent.owner_id)
    if scope.name == "mine":  # every agent of the viewer's, bound to a project yet or not
        stmt = stmt.where(Agent.owner_id == scope.user.id)
    elif scope.project_ids is not None:
        stmt = stmt.where(exists(select(AgentBinding.id).where(
            AgentBinding.agent_id == Agent.id, AgentBinding.project_id.in_(scope.project_ids))))
    found = (await db.execute(stmt)).all()
    if not found:
        return []
    statuses = await agent_statuses(db, [agent_id for agent_id, _, _ in found])
    # only runs in scope: an agent bound to several projects shows none of another project's work
    today_runs = dict((await db.execute(
        _runs(scope, AgentRun.agent_id, func.count())
        .where(AgentRun.agent_id.in_([a for a, _, _ in found]), AgentRun.started_at >= scope.day_start(scope.today()))
        .group_by(AgentRun.agent_id)
    )).all())
    # working here means running in scope, as Running now shows; busy only elsewhere is told apart
    here = set((await db.execute(
        _runs(scope, AgentRun.agent_id)
        .where(AgentRun.agent_id.in_([a for a, _, _ in found]), AgentRun.status == RunStatus.running)
    )).scalars())
    for agent_id in statuses:
        if statuses[agent_id] == "busy" and agent_id not in here:
            statuses[agent_id] = "busy_elsewhere"
    items = [AgentItem(id=agent_id, name=name, status=statuses[agent_id], runs_today=today_runs.get(agent_id, 0),
                       owner_id=owner_id, runner=runner_info(agent_id))
             for agent_id, name, owner_id in found]
    return sorted(items, key=lambda a: (_ORDER[a.status], a.name.lower()))


async def running(db: AsyncSession, scope: Scope) -> list[RunningItem]:
    return await running_items(db, _in_scope(scope))


async def queued(db: AsyncSession, scope: Scope) -> Queued:
    where = AgentRun.status == RunStatus.queued
    total = await db.scalar(_runs(scope, func.count()).where(where))
    rows = (await db.execute(
        _runs(scope, Project.key, Task.number, AgentRun.stage)
        .outerjoin(Project, Project.id == Task.project_id)
        .where(where).order_by(AgentRun.created_at, AgentRun.id).limit(QUEUED_SHOWN)
    )).all()
    return Queued(total=total or 0, items=[
        QueuedItem(task_key=f"{key}-{number}" if key else None, stage=stage,
                   link=task_link(key, number) if key else None)
        for key, number, stage in rows
    ])


async def failed_runs(db: AsyncSession, scope: Scope) -> tuple[int, float | None]:
    """(runs failed in the last 24 hours, completed / (completed + failed) over the same window)."""
    recent = AgentRun.finished_at >= datetime.now(UTC) - timedelta(hours=24)
    completed, failed = (await db.execute(_runs(
        scope,
        func.count().filter(recent, AgentRun.status == RunStatus.completed),
        func.count().filter(recent, AgentRun.status == RunStatus.failed),
    ))).one()
    return failed, (completed / (completed + failed) if completed + failed else None)
