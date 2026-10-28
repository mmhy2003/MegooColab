import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.audit import service as audit
from app.auth.deps import AuthedUser
from app.auth.models import User
from app.core.db import DbSession
from app.core.events import Event, publish
from app.projects.access import get_project_for, require_manage
from app.sprints import service
from app.sprints.models import Sprint, SprintState
from app.sprints.schemas import (
    BurndownPoint,
    CompleteIn,
    SprintIn,
    SprintOut,
    SprintPatch,
    TaskSprintIn,
    VelocityPoint,
)
from app.tasks import service as task_service
from app.tasks.schemas import TaskOut

router = APIRouter(tags=["sprints"])


async def _changed(db, sprint: Sprint) -> None:
    await publish(db, Event(type="sprint.updated", project_id=sprint.project_id))


async def _sprint_for(db, user: User, sprint_id: uuid.UUID, manage: bool = False) -> Sprint:
    sprint = await service.get_sprint(db, sprint_id)
    project = await get_project_for(db, user, str(sprint.project_id), write=manage)
    service.require_sprints(project)
    if manage:
        await require_manage(db, user, project)
    return sprint


@router.get("/api/projects/{ref}/sprints")
async def list_sprints(ref: str, user: AuthedUser, db: DbSession) -> list[SprintOut]:
    project = await get_project_for(db, user, ref)
    service.require_sprints(project)
    rows = await db.execute(
        select(Sprint).where(Sprint.project_id == project.id).order_by(Sprint.start_date, Sprint.created_at)
    )
    return [SprintOut.model_validate(s) for s in rows.scalars()]


@router.post("/api/projects/{ref}/sprints", status_code=status.HTTP_201_CREATED)
async def create_sprint(ref: str, body: SprintIn, user: AuthedUser, db: DbSession) -> SprintOut:
    project = await get_project_for(db, user, ref, write=True)
    service.require_sprints(project)
    await require_manage(db, user, project)
    sprint = Sprint(project_id=project.id, **body.model_dump())
    db.add(sprint)
    await db.flush()
    await db.refresh(sprint)
    await _changed(db, sprint)
    return SprintOut.model_validate(sprint)


@router.patch("/api/sprints/{sprint_id}")
async def update_sprint(sprint_id: uuid.UUID, body: SprintPatch, user: AuthedUser, db: DbSession) -> SprintOut:
    sprint = await _sprint_for(db, user, sprint_id, manage=True)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(sprint, field, value)
    if sprint.end_date < sprint.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end_before_start")
    await _changed(db, sprint)
    return SprintOut.model_validate(sprint)


@router.post("/api/sprints/{sprint_id}/start")
async def start_sprint(sprint_id: uuid.UUID, user: AuthedUser, db: DbSession) -> SprintOut:
    sprint = await _sprint_for(db, user, sprint_id, manage=True)
    await service.start(db, sprint)
    await _changed(db, sprint)
    return SprintOut.model_validate(sprint)


@router.post("/api/sprints/{sprint_id}/complete")
async def complete_sprint(sprint_id: uuid.UUID, body: CompleteIn, user: AuthedUser, db: DbSession) -> SprintOut:
    sprint = await _sprint_for(db, user, sprint_id, manage=True)
    await service.complete(db, sprint, body.move_open_to)
    await _changed(db, sprint)
    return SprintOut.model_validate(sprint)


@router.delete("/api/sprints/{sprint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sprint(sprint_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    """Its tasks lose the sprint (ON DELETE SET NULL): open ones are back in the backlog. Its snapshots go with it."""
    sprint = await _sprint_for(db, user, sprint_id, manage=True)
    await audit.record(db, "sprint.deleted", actor_id=user.id, target_type="sprint", target_id=sprint.id,
                       data={"name": sprint.name})
    await _changed(db, sprint)
    await db.delete(sprint)


@router.get("/api/sprints/{sprint_id}/burndown")
async def sprint_burndown(sprint_id: uuid.UUID, user: AuthedUser, db: DbSession) -> list[BurndownPoint]:
    return await service.burndown(db, await _sprint_for(db, user, sprint_id))


@router.get("/api/projects/{ref}/velocity")
async def velocity(
    ref: str, user: AuthedUser, db: DbSession, last: int = Query(default=6, ge=1, le=50)
) -> list[VelocityPoint]:
    project = await get_project_for(db, user, ref)
    service.require_sprints(project)
    rows = (
        await db.execute(
            select(Sprint)
            .where(Sprint.project_id == project.id, Sprint.state == SprintState.completed)
            .order_by(Sprint.completed_at.desc())
            .limit(last)
        )
    ).scalars().all()
    return [
        VelocityPoint(sprint_id=s.id, name=s.name, committed_points=s.committed_points or 0,
                      completed_points=s.completed_points or 0)
        for s in reversed(rows)
    ]


@router.put("/api/tasks/{key}/sprint")
async def set_task_sprint(key: str, body: TaskSprintIn, user: AuthedUser, db: DbSession) -> TaskOut:
    task, project = await task_service.get_task_for(db, user, key, write=True)
    service.require_sprints(project)
    if task.type not in service.SPRINTABLE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_sprintable")
    if body.sprint_id is not None:
        target = await db.get(Sprint, body.sprint_id)
        if target is None or target.project_id != project.id or target.state == SprintState.completed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_sprint")
    previous = task.sprint_id
    if previous != body.sprint_id:
        task.sprint_id = body.sprint_id
        await task_service.record_event(db, task, user.id, "sprint_changed", {
            "from": str(previous) if previous else None,
            "to": str(body.sprint_id) if body.sprint_id else None,
        })
        await service.snapshot_if_active(db, previous)
        await service.snapshot_if_active(db, body.sprint_id)
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
    return await task_service.task_out(db, task, user)
