"""Board rules (WF-2, AGT-12): what dragging a card or changing its agent does to the task's workflow.

Called by app/tasks/service.py before the move or reassignment is applied, so a refusal changes nothing.
Only runner-driven workflows are governed here; a manual checklist (WF-11) never holds the card.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.projects.models import BoardColumn, ColumnCategory
from app.tasks.models import Task
from app.workflow import engine
from app.workflow.models import Driver, WorkflowStatus


async def before_move(db: AsyncSession, user: User, task: Task, to: BoardColumn) -> None:
    """A human moves the card into `to`:
    - into review or done while a workflow is not finished: 409 workflow_controls_column;
    - from a non-working column into working: an idle (or no) workflow starts, a paused one resumes
      (403 cannot_use_agent if the mover cannot use the agent);
    - from working into before: an active workflow pauses."""
    if to.id == task.column_id:
        return
    frm = (await db.get(BoardColumn, task.column_id)).category
    wf = await engine.lock_task(db, task)
    runner = wf is not None and wf.driver == Driver.runner
    if to.category in (ColumnCategory.review, ColumnCategory.done):
        if runner and wf.status != WorkflowStatus.finished:
            raise HTTPException(status.HTTP_409_CONFLICT, "workflow_controls_column")
        return
    if to.category == ColumnCategory.working and frm != ColumnCategory.working:
        if task.assignee_agent_id is None:
            return
        if wf is None or wf.status == WorkflowStatus.idle:
            await engine.start(db, user, task)
        elif runner and wf.status == WorkflowStatus.paused:
            await engine.resume(db, user, task)
    elif (
        to.category == ColumnCategory.before and frm == ColumnCategory.working
        and runner and wf.status in engine.ACTIVE
    ):
        await engine.pause(db, user, task)


async def before_reassign(db: AsyncSession, task: Task, new_agent_id: uuid.UUID | None) -> None:
    """The task's agent assignee changes: 409 workflow_active while the workflow runs or waits; a paused
    workflow forgets its sessions (they belong to the old agent)."""
    if new_agent_id == task.assignee_agent_id:
        return
    wf = await engine.lock_task(db, task)
    if wf is None or wf.driver != Driver.runner:
        return
    if wf.status in engine.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_active")
    if wf.status == WorkflowStatus.paused:
        wf.sessions.clear()
        wf.agent_id = new_agent_id
