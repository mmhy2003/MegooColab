"""A project's status: closing it (Finished, Archived) stops the work in it; reopening leaves that work paused."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth.models import User
from app.projects.models import Project, ProjectStatus
from app.tasks.models import Task
from app.workflow import engine
from app.workflow.models import Driver, TaskWorkflow


async def active_workflow_tasks(db: AsyncSession, project_id) -> list[Task]:
    """Tasks whose workflow Pause applies to: running or waiting for a person, under any driver but manual."""
    rows = await db.execute(
        select(Task)
        .join(TaskWorkflow, TaskWorkflow.task_id == Task.id)
        .where(Task.project_id == project_id, TaskWorkflow.status.in_(engine.ACTIVE),
               TaskWorkflow.driver != Driver.manual)
        .order_by(Task.id)
    )
    return list(rows.scalars())


async def set_status(db: AsyncSession, user: User, project: Project, status: ProjectStatus) -> bool:
    """Returns whether anything changed. Leaving Active pauses every workflow in progress, as the person closing."""
    old = ProjectStatus(project.status)
    if old == status:
        return False
    if old == ProjectStatus.active:
        # one at a time, in id order: pause takes each task's and workflow's locks itself
        for task in await active_workflow_tasks(db, project.id):
            await engine.pause(db, user, task)
    project.status = status
    await audit.record(db, "project.status_changed", actor_id=user.id, target_type="project", target_id=project.id,
                       data={"from": old.value, "to": status.value})
    return True
