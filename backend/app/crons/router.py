import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.crons import schedule, service
from app.crons.models import Cron, CronRun
from app.crons.schemas import CronIn, CronOut, CronPatch, CronRunOut, Preview, PreviewIn
from app.projects.access import get_project_for, require_manage

router = APIRouter(tags=["crons"])

PREVIEW_COUNT = 3


@router.post("/api/crons/preview")
async def preview(body: PreviewIn, user: AuthedUser) -> Preview:
    """What a schedule means, for the editor as it is typed: never a 422, the error is in the answer."""
    try:
        schedule.check(body.schedule, body.timezone)
    except HTTPException as e:
        return Preview(ok=False, error=e.detail["message"], description=None, next=[])
    return Preview(ok=True, error=None, description=schedule.describe(body.schedule),
                   next=schedule.next_times(body.schedule, body.timezone, datetime.now(UTC), PREVIEW_COUNT))


# -- a project's crons: its members read, its managers and admins write ------------------------------


async def _managed(db, user, ref: str):
    project = await get_project_for(db, user, ref, write=True)
    await require_manage(db, user, project)
    return project


@router.get("/api/projects/{ref}/crons")
async def list_crons(ref: str, user: AuthedUser, db: DbSession) -> list[CronOut]:
    project = await get_project_for(db, user, ref)
    crons = (await db.execute(select(Cron).where(Cron.project_id == project.id).order_by(Cron.name))).scalars().all()
    return [await service.cron_out(db, c) for c in crons]


@router.post("/api/projects/{ref}/crons", status_code=status.HTTP_201_CREATED)
async def create_cron(ref: str, body: CronIn, user: AuthedUser, db: DbSession) -> CronOut:
    project = await _managed(db, user, ref)
    cron = await service.create(db, user, project, body)
    await db.commit()
    return await service.cron_out(db, cron)


@router.get("/api/projects/{ref}/crons/{cron_id}")
async def get_cron(ref: str, cron_id: uuid.UUID, user: AuthedUser, db: DbSession) -> CronOut:
    project = await get_project_for(db, user, ref)
    return await service.cron_out(db, await service.get_cron(db, project, cron_id))


@router.patch("/api/projects/{ref}/crons/{cron_id}")
async def edit_cron(ref: str, cron_id: uuid.UUID, body: CronPatch, user: AuthedUser, db: DbSession) -> CronOut:
    project = await _managed(db, user, ref)
    cron = await service.update(db, user, project, await service.get_cron(db, project, cron_id, lock=True), body)
    await db.commit()
    return await service.cron_out(db, cron)


@router.delete("/api/projects/{ref}/crons/{cron_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cron(ref: str, cron_id: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    project = await get_project_for(db, user, ref)  # a finished project's crons can still be removed
    await require_manage(db, user, project)
    await service.delete(db, user, await service.get_cron(db, project, cron_id, lock=True))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/projects/{ref}/crons/{cron_id}/pause")
async def pause_cron(ref: str, cron_id: uuid.UUID, user: AuthedUser, db: DbSession) -> CronOut:
    project = await _managed(db, user, ref)
    cron = await service.set_paused(db, user, await service.get_cron(db, project, cron_id, lock=True), True)
    await db.commit()
    return await service.cron_out(db, cron)


@router.post("/api/projects/{ref}/crons/{cron_id}/resume")
async def resume_cron(ref: str, cron_id: uuid.UUID, user: AuthedUser, db: DbSession) -> CronOut:
    project = await _managed(db, user, ref)
    cron = await service.set_paused(db, user, await service.get_cron(db, project, cron_id, lock=True), False)
    await db.commit()
    return await service.cron_out(db, cron)


@router.get("/api/projects/{ref}/crons/{cron_id}/runs")
async def cron_runs(ref: str, cron_id: uuid.UUID, user: AuthedUser, db: DbSession,
                    limit: int = Query(default=50, ge=1, le=200)) -> list[CronRunOut]:
    project = await get_project_for(db, user, ref)
    return await service.runs(db, await service.get_cron(db, project, cron_id), limit)


@router.get("/api/projects/{ref}/crons/{cron_id}/runs/{run_id}")
async def cron_run(ref: str, cron_id: uuid.UUID, run_id: uuid.UUID, user: AuthedUser, db: DbSession) -> CronRunOut:
    project = await get_project_for(db, user, ref)
    cron = await service.get_cron(db, project, cron_id)
    run = await db.get(CronRun, run_id)
    if run is None or run.cron_id != cron.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cron_run_not_found")
    return await service.run_out(db, run)
