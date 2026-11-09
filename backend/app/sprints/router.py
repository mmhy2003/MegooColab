import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.projects.access import get_project_for
from app.sprints import actions, service
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


_changed = actions.changed
_sprint_for = actions.sprint_for


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
    return SprintOut.model_validate(await actions.create(db, user, project, body))


@router.patch("/api/sprints/{sprint_id}")
async def update_sprint(sprint_id: uuid.UUID, body: SprintPatch, user: AuthedUser, db: DbSession) -> SprintOut:
    sprint = await _sprint_for(db, user, sprint_id, manage=True)
    return SprintOut.model_validate(await actions.update(db, sprint, body))


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
    await actions.delete(db, user, await _sprint_for(db, user, sprint_id, manage=True))


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
    await actions.set_task_sprint(db, user, project, task, body.sprint_id)
    return await task_service.task_out(db, task, user)
