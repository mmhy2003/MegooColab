"""Live mockups (WF-6d): an agent shows the next version of a screen without asking or ending its turn.

Viewers see it through the `mockup.shown` task event. Nothing new can be shown while a design awaits approval:
the version a person approves is the one the pending design was submitted with.
"""

from fastapi import HTTPException, status
from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.tasks.models import Task
from app.workflow import engine, questions
from app.workflow.models import (
    DocKind,
    DocStatus,
    Mockup,
    Needs,
    TaskWorkflow,
    WorkflowDocument,
)


async def show(db, run: AgentRun | None, task: Task, html: str, title: str) -> Mockup:
    """Store the task's next mockup version. The caller holds the workflow lock and commits."""
    clean = questions._clean_mockup({"html": html, "title": title, "choices": []})
    if await _design_pending(db, run, task):
        raise HTTPException(status.HTTP_409_CONFLICT, "design_submitted")
    row = await questions.next_mockup(db, task, clean)
    await engine.record_workflow_event(db, task, None, "mockup.shown", {"version": row.version, "title": row.title})
    return row


async def _design_pending(db, run: AgentRun | None, task: Task) -> bool:
    """A submitted design something waits on: a human's approval, or the end of the run that just submitted it.
    A design left submitted by an earlier workflow (handed over to the runner) waits on nothing and blocks
    nothing; the next submission supersedes it."""
    pending = (
        await db.execute(
            select(WorkflowDocument.submitted_run_id)
            .where(
                WorkflowDocument.task_id == task.id,
                WorkflowDocument.kind == DocKind.design,
                WorkflowDocument.status == DocStatus.submitted,
            )
            .limit(1)
        )
    ).first()
    if pending is None:
        return False
    wf = await db.get(TaskWorkflow, task.id)
    if wf is not None and wf.needs == Needs.design_approval:
        return True
    return run is not None and pending.submitted_run_id == run.id
