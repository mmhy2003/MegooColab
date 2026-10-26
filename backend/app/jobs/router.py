import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.deps import AdminUser
from app.core.db import DbSession
from app.jobs.models import Job, JobStatus

router = APIRouter(tags=["jobs"])


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: JobStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    finished_at: datetime | None


@router.get("/api/admin/jobs", response_model=list[JobOut])
async def list_jobs(db: DbSession, _admin: AdminUser, status: JobStatus | None = None) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(100)
    if status is not None:
        stmt = stmt.where(Job.status == status)
    return list((await db.execute(stmt)).scalars())
