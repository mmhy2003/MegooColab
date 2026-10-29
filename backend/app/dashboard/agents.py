"""Agents and their runs: who is working, idle or offline, what is running and queued, and failed runs. A run is in
scope through its task's project, or (a run answering another project's question) the question's target project."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.a2a.models import Question
from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent, AgentBinding
from app.agents.service import agent_statuses
from app.dashboard.schemas import AgentItem, Queued, QueuedItem, RunningItem
from app.dashboard.scope import Scope, task_link
from app.projects.models import Project
from app.tasks.models import Task
from app.workflow.models import DocKind, DocStatus, Stage, TaskWorkflow, WorkflowDocument

QUEUED_SHOWN = 5
_ORDER = {"busy": 0, "busy_elsewhere": 1, "online": 2, "offline": 3}


def _runs(scope: Scope, *columns):
    """A select over runs in scope, with the run's task (if any) and question (if any) joined."""
    stmt = (
        select(*columns).select_from(AgentRun)
        .outerjoin(Task, Task.id == AgentRun.task_id).outerjoin(Question, Question.id == AgentRun.question_id)
        .where(scope.in_projects(func.coalesce(Task.project_id, Question.target_project_id)))
    )
    if scope.name == "mine":
        stmt = stmt.where(AgentRun.agent_id.in_(scope.agent_ids))
    return stmt


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
    statuses = await agent_statuses(db, [(agent_id, owner_id) for agent_id, _, owner_id in found])
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
    items = [AgentItem(id=agent_id, name=name, status=statuses[agent_id], runs_today=today_runs.get(agent_id, 0))
             for agent_id, name, _ in found]
    return sorted(items, key=lambda a: (_ORDER[a.status], a.name.lower()))


async def running(db: AsyncSession, scope: Scope) -> list[RunningItem]:
    asking_task, asking_project = aliased(Task), aliased(Project)
    steps_total = (
        select(func.jsonb_array_length(WorkflowDocument.steps))
        .where(WorkflowDocument.task_id == AgentRun.task_id, WorkflowDocument.kind == DocKind.plan,
               WorkflowDocument.status == DocStatus.approved)
        .order_by(WorkflowDocument.version.desc()).limit(1).scalar_subquery()
    )
    stmt = (
        _runs(scope, AgentRun.id, Agent.name, AgentRun.started_at, Project.key, Task.number, AgentRun.stage,
              AgentRun.step, steps_total, TaskWorkflow.review_round, AgentRun.question_id, asking_project.key)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .outerjoin(Project, Project.id == Task.project_id)
        .outerjoin(TaskWorkflow, TaskWorkflow.task_id == AgentRun.task_id)
        .outerjoin(asking_task, asking_task.id == Question.from_task_id)
        .outerjoin(asking_project, asking_project.id == asking_task.project_id)
        .where(AgentRun.status == RunStatus.running)
        .order_by(AgentRun.started_at.desc().nulls_last())
    )
    out = []
    for run_id, name, started, key, number, stage, step, total, rounds, question_id, asked_from in (
        await db.execute(stmt)
    ).all():
        out.append(RunningItem(
            run_id=run_id, agent_name=name, started_at=started, task_key=f"{key}-{number}" if key else None,
            stage=stage, step=step if stage == Stage.build else None,
            steps_total=total if stage == Stage.build else None,
            review_round=rounds if stage == Stage.review else None,
            question_from=asked_from if question_id else None,
            link=task_link(key, number) if key else f"/questions/{question_id}",
        ))
    return out


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
