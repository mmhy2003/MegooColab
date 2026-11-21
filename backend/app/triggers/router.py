import uuid

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.projects.access import get_project_for, require_manage
from app.triggers import service
from app.triggers.models import Trigger
from app.triggers.schemas import FiringOut, TriggerIn, TriggerOut, TriggerPatch
from app.workflow import engine

router = APIRouter(tags=["triggers"])

# a project's triggers: its members read, its managers and admins write


async def _managed(db, user, ref: str):
    project = await get_project_for(db, user, ref, write=True)
    await require_manage(db, user, project)
    return project


async def _managed_any_status(db, user, ref: str):
    """A project's managers may pause, resume and delete its triggers even once it is finished or archived."""
    project = await get_project_for(db, user, ref)
    await require_manage(db, user, project)
    return project


@router.get("/api/projects/{ref}/triggers")
async def list_triggers(ref: str, user: AuthedUser, db: DbSession) -> list[TriggerOut]:
    project = await get_project_for(db, user, ref)
    triggers = (await db.execute(
        select(Trigger).where(Trigger.project_id == project.id).order_by(Trigger.name, Trigger.created_at)
    )).scalars().all()
    return [await service.trigger_out(db, t) for t in triggers]


@router.post("/api/projects/{ref}/triggers", status_code=status.HTTP_201_CREATED)
async def create_trigger(ref: str, body: TriggerIn, user: AuthedUser, db: DbSession) -> TriggerOut:
    project = await _managed(db, user, ref)
    trigger = await service.create(db, user, project, body)
    await db.commit()
    return await service.trigger_out(db, trigger)


@router.get("/api/projects/{ref}/triggers/{trigger_id}")
async def get_trigger(ref: str, trigger_id: uuid.UUID, user: AuthedUser, db: DbSession) -> TriggerOut:
    project = await get_project_for(db, user, ref)
    return await service.trigger_out(db, await service.get_trigger(db, project, trigger_id))


@router.patch("/api/projects/{ref}/triggers/{trigger_id}")
async def edit_trigger(ref: str, trigger_id: uuid.UUID, body: TriggerPatch, user: AuthedUser,
                       db: DbSession) -> TriggerOut:
    project = await _managed(db, user, ref)
    trigger = await service.update(db, user, project, await service.get_trigger(db, project, trigger_id, lock=True),
                                   body)
    await db.commit()
    return await service.trigger_out(db, trigger)


@router.delete("/api/projects/{ref}/triggers/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trigger(ref: str, trigger_id: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    project = await _managed_any_status(db, user, ref)
    await service.delete(db, user, await service.get_trigger(db, project, trigger_id, lock=True))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/projects/{ref}/triggers/{trigger_id}/pause")
async def pause_trigger(ref: str, trigger_id: uuid.UUID, user: AuthedUser, db: DbSession) -> TriggerOut:
    project = await _managed_any_status(db, user, ref)
    trigger = await service.set_paused(db, user, await service.get_trigger(db, project, trigger_id, lock=True), True)
    await db.commit()
    return await service.trigger_out(db, trigger)


@router.post("/api/projects/{ref}/triggers/{trigger_id}/resume")
async def resume_trigger(ref: str, trigger_id: uuid.UUID, user: AuthedUser, db: DbSession) -> TriggerOut:
    project = await _managed_any_status(db, user, ref)
    trigger = await service.set_paused(db, user, await service.get_trigger(db, project, trigger_id, lock=True), False)
    await db.commit()
    return await service.trigger_out(db, trigger)


@router.post("/api/projects/{ref}/triggers/{trigger_id}/try", status_code=status.HTTP_201_CREATED)
async def try_trigger(ref: str, trigger_id: uuid.UUID, user: AuthedUser, db: DbSession) -> FiringOut:
    project = await _managed(db, user, ref)
    firing = await service.try_now(db, user, project, await service.get_trigger(db, project, trigger_id, lock=True))
    await db.commit()
    await engine.dispatch_queued(db)
    return await service.firing_out(db, firing)


@router.get("/api/projects/{ref}/triggers/{trigger_id}/firings")
async def list_firings(ref: str, trigger_id: uuid.UUID, user: AuthedUser, db: DbSession,
                       limit: int = Query(default=50, ge=1, le=200)) -> list[FiringOut]:
    project = await get_project_for(db, user, ref)
    trigger = await service.get_trigger(db, project, trigger_id)
    return [await service.firing_out(db, f) for f in await service.firings(db, trigger, limit)]
