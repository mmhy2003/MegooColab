"""Live mockups (WF-6d): an agent shows the next version of a screen without asking or ending its turn.

Viewers see it through the `mockup.shown` task event. Nothing new can be shown while a design awaits approval:
the version a person approves is the one the pending design was submitted with.
"""

from fastapi import HTTPException, status
from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.tasks.models import Task
from app.workflow import engine, questions
from app.workflow.models import DocKind, DocStatus, Mockup, WorkflowDocument


async def show(db, run: AgentRun | None, task: Task, html: str, title: str) -> Mockup:
    """Store the task's next mockup version. The caller holds the workflow lock and commits."""
    clean = questions._clean_mockup({"html": html, "title": title, "choices": []})
    pending = await db.scalar(
        select(WorkflowDocument.id)
        .where(
            WorkflowDocument.task_id == task.id,
            WorkflowDocument.kind == DocKind.design,
            WorkflowDocument.status == DocStatus.submitted,
        )
        .limit(1)
    )
    if pending is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "design_submitted")
    row = await questions.next_mockup(db, task, clean)
    await engine.record_workflow_event(db, task, None, "mockup.shown", {"version": row.version, "title": row.title})
    return row
