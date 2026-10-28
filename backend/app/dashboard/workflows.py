"""Workflows by stage: those started and not finished, split by whether an agent works, a person is waited on, or the
workflow is paused or driven by hand; plus how many finished in the last 30 days."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dashboard.schemas import StageRow, Stages
from app.dashboard.scope import Scope
from app.tasks.models import Task
from app.workflow.models import Stage, TaskWorkflow, WorkflowStatus

DONE_DAYS = 30


async def stages(db: AsyncSession, scope: Scope) -> tuple[Stages, int, int]:
    """(the stage bars, workflows in progress, how many projects they are in)."""
    in_scope = (scope.in_projects(Task.project_id), scope.mine_tasks())
    status = TaskWorkflow.status
    in_progress = and_(TaskWorkflow.started_at.is_not(None), status != WorkflowStatus.finished)
    rows = (await db.execute(
        select(
            TaskWorkflow.stage,
            func.count().filter(status == WorkflowStatus.running),
            func.count().filter(status == WorkflowStatus.waiting_human),
            func.count().filter(status.in_((WorkflowStatus.paused, WorkflowStatus.idle))),
        )
        .join(Task, Task.id == TaskWorkflow.task_id).where(in_progress, *in_scope).group_by(TaskWorkflow.stage)
    )).all()
    by_stage = {stage: (running, waiting, paused) for stage, running, waiting, paused in rows}
    total, projects, done = (await db.execute(
        select(
            func.count().filter(in_progress),
            func.count(distinct(Task.project_id)).filter(in_progress),
            func.count().filter(status == WorkflowStatus.finished,
                                TaskWorkflow.finished_at >= datetime.now(UTC) - timedelta(days=DONE_DAYS)),
        )
        .join(Task, Task.id == TaskWorkflow.task_id).where(*in_scope)
    )).one()
    bars = [StageRow(stage=s, running=by_stage.get(s, (0, 0, 0))[0], waiting=by_stage.get(s, (0, 0, 0))[1],
                     paused=by_stage.get(s, (0, 0, 0))[2]) for s in Stage]
    return Stages(rows=bars, done_30d=done), total, projects
