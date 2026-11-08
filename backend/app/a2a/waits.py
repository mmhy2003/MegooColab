"""Waiting on another project's answer.

An agent asks with `wait=True` when it can't go on without the answer. The wait is decided when one of the task's
runs ends, not when the agent asks, and it belongs to the task: while any of its `wait` questions is open, a run that
ended without its role's own outcome leaves the workflow waiting (`Needs.project_answer`), quietly: nobody is asked.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.models import OPEN_STATUSES, Question
from app.agent_runs.models import AgentRun
from app.tasks.models import Task
from app.workflow.models import (
    DocStatus,
    Needs,
    RunRole,
    StepReview,
    TaskWorkflow,
    WorkflowDocument,
)


async def open_waits(db: AsyncSession, task_id) -> list[Question]:
    """The task's questions it can't go on without, still open, oldest first."""
    rows = await db.execute(
        select(Question)
        .where(Question.from_task_id == task_id, Question.wait.is_(True), Question.status.in_(OPEN_STATUSES))
        .order_by(Question.created_at, Question.id)
    )
    return list(rows.scalars())


async def produced_outcome(db: AsyncSession, run: AgentRun) -> bool:
    """Did the run leave its role's own outcome (a question for a person, a document, a review, a step result)?
    Then its role's handler decides what comes next, and any open wait holds the task only at a later run's end."""
    from app.workflow import questions  # local: questions imports the engine, which imports this module lazily

    if run.step_result:
        return True
    if await questions.has_open_question(db, run.id):
        return True
    submitted = await db.scalar(
        select(WorkflowDocument.id)
        .where(WorkflowDocument.submitted_run_id == run.id, WorkflowDocument.status == DocStatus.submitted)
        .limit(1)
    )
    if submitted is not None:
        return True
    return await db.scalar(select(StepReview.id).where(StepReview.run_id == run.id).limit(1)) is not None


async def hold_after_run(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> bool:
    """Called at a run's normal end, before its role's handler. True: the end is handled (the task waits)."""
    from app.workflow import engine  # local: the engine imports this module lazily

    if RunRole(run.workflow_role) == RunRole.finish or await produced_outcome(db, run):
        return False
    if await open_waits(db, task.id):
        await engine.wait_for(db, wf, Needs.project_answer, notify=False)
        return True
    return False
