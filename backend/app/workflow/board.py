"""Board rules (WF-2, AGT-12): what dragging a card or changing its agent does to the task's workflow.

Called by app/tasks/service.py before the move or reassignment is applied, so a refusal changes nothing.
Runner-driven workflows are governed here, and an active connect-only one (AGT-32) holds its card and its
assignee too; a manual checklist (WF-11) never holds the card.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.projects.models import BoardColumn, ColumnCategory
from app.tasks.models import Task, TaskType
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
    runner = wf is not None and wf.driver == Driver.runner and wf.status != WorkflowStatus.idle
    connect_only = wf is not None and wf.driver == Driver.connect_only and wf.status in engine.ACTIVE
    if to.category in (ColumnCategory.review, ColumnCategory.done):
        if (runner and wf.status != WorkflowStatus.finished) or connect_only:
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


async def before_reassign(
    db: AsyncSession, task: Task, new_agent_id: uuid.UUID | None, new_user_id: uuid.UUID | None
) -> None:
    """The task's assignee changes:
    - an active connect-only workflow (AGT-32): 409 workflow_active for any change, as its assignee drives it
      and may act on it (WF-6). Once paused it may go to another person (whose stage tools resume it) or to an
      agent, which makes it an idle runner workflow at brainstorm (engine.hand_over_to_runner);
    - a runner-driven workflow, when the agent changes: 409 workflow_active while it runs or waits; a paused
      workflow forgets its sessions (they belong to the old agent)."""
    if (new_agent_id, new_user_id) == (task.assignee_agent_id, task.assignee_user_id):
        return
    wf = await engine.lock_task(db, task)
    if wf is not None and wf.driver == Driver.connect_only:
        if wf.status in engine.ACTIVE:
            raise HTTPException(status.HTTP_409_CONFLICT, "workflow_active")
        if wf.status == WorkflowStatus.paused and new_agent_id is not None:
            engine.hand_over_to_runner(wf)
        return
    if wf is None or wf.driver != Driver.runner or new_agent_id == task.assignee_agent_id:
        return
    if wf.status in engine.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_active")
    if wf.status == WorkflowStatus.paused:
        wf.sessions.clear()
        wf.agent_id = new_agent_id


async def before_type_change(db: AsyncSession, task: Task, new_type: TaskType) -> None:
    """A task with a started, unfinished workflow cannot become an epic or a subtask: its plan's subtasks
    could not be created under it."""
    if new_type in engine.WORKFLOW_TYPES:
        return
    wf = await engine.lock_task(db, task)
    if wf is not None and wf.status not in (WorkflowStatus.idle, WorkflowStatus.finished):
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_active")
