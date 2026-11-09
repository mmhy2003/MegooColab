"""What people (REST) and agents (MCP) do to sprints, with the same rights checks: managing a sprint needs the
project's manage rights, putting a task in one needs write access to the task."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth.models import User
from app.core.events import Event, publish
from app.projects.access import get_project_for, require_manage
from app.projects.models import Project
from app.sprints import service
from app.sprints.models import Sprint, SprintState
from app.sprints.schemas import SprintIn, SprintPatch
from app.tasks import service as task_service
from app.tasks.models import Task


async def changed(db: AsyncSession, sprint: Sprint) -> None:
    await publish(db, Event(type="sprint.updated", project_id=sprint.project_id))


async def sprint_for(db: AsyncSession, user: User, sprint_id: uuid.UUID, manage: bool = False) -> Sprint:
    sprint = await service.get_sprint(db, sprint_id)
    project = await get_project_for(db, user, str(sprint.project_id), write=manage)
    service.require_sprints(project)
    if manage:
        await require_manage(db, user, project)
    return sprint


async def sprint_named(db: AsyncSession, project: Project, name: str) -> Sprint:
    """A project's sprint by name, ignoring case (sprint_not_found)."""
    rows = (await db.execute(select(Sprint).where(Sprint.project_id == project.id))).scalars()
    for sprint in rows:
        if sprint.name.casefold() == name.strip().casefold():
            return sprint
    raise HTTPException(status.HTTP_404_NOT_FOUND, "sprint_not_found")


async def create(db: AsyncSession, user: User, project: Project, body: SprintIn) -> Sprint:
    service.require_sprints(project)
    await require_manage(db, user, project)
    sprint = Sprint(project_id=project.id, **body.model_dump())
    db.add(sprint)
    await db.flush()
    await db.refresh(sprint)
    await changed(db, sprint)
    return sprint


async def update(db: AsyncSession, sprint: Sprint, body: SprintPatch) -> Sprint:
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(sprint, field, value)
    if sprint.end_date < sprint.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end_before_start")
    await changed(db, sprint)
    return sprint


async def delete(db: AsyncSession, user: User, sprint: Sprint) -> None:
    """Its tasks lose the sprint (ON DELETE SET NULL): open ones are back in the backlog. Its snapshots go with it."""
    await audit.record(db, "sprint.deleted", actor_id=user.id, target_type="sprint", target_id=sprint.id,
                       data={"name": sprint.name})
    await changed(db, sprint)
    await db.delete(sprint)


async def set_task_sprint(db: AsyncSession, user: User, project: Project, task: Task,
                          sprint_id: uuid.UUID | None) -> None:
    service.require_sprints(project)
    if task.type not in service.SPRINTABLE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_sprintable")
    if sprint_id is not None:
        target = await db.get(Sprint, sprint_id)
        if target is None or target.project_id != project.id or target.state == SprintState.completed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_sprint")
    previous = task.sprint_id
    if previous != sprint_id:
        task.sprint_id = sprint_id
        await task_service.record_event(db, task, user.id, "sprint_changed", {
            "from": str(previous) if previous else None,
            "to": str(sprint_id) if sprint_id else None,
        })
        await service.snapshot_if_active(db, previous)
        await service.snapshot_if_active(db, sprint_id)
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
