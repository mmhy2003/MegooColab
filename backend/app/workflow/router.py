import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import service as audit
from app.auth.deps import AdminUser, AuthedUser
from app.core.db import DbSession
from app.core.text import NoNulStr
from app.workflow import methodology
from app.workflow.models import MethodologyVersion, Stage

router = APIRouter(prefix="/api/methodology", tags=["workflow"])


class MethodologyOut(BaseModel):
    key: str
    stage: Stage
    version: int
    body_md: str
    updated_at: datetime
    updated_by: uuid.UUID | None


class MethodologyVersionInfo(BaseModel):
    version: int
    created_at: datetime
    created_by: uuid.UUID | None


class MethodologyVersionOut(MethodologyVersionInfo):
    key: str
    body_md: str


class MethodologyIn(BaseModel):
    body_md: NoNulStr = Field(min_length=1, max_length=50_000)


def _out(row: MethodologyVersion) -> MethodologyOut:
    return MethodologyOut(
        key=row.key, stage=methodology.STAGE_OF[row.key], version=row.version,
        body_md=row.body_md, updated_at=row.created_at, updated_by=row.created_by,
    )


def _known(key: str) -> None:
    if key not in methodology.STAGE_OF:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "methodology_not_found")


@router.get("")
async def list_methodology(user: AuthedUser, db: DbSession) -> list[MethodologyOut]:
    out = []
    for key in methodology.ALL_KEYS:
        try:
            out.append(_out(await methodology.current(db, key)))
        except LookupError:
            continue
    return out


@router.get("/{key}/versions")
async def list_versions(key: str, user: AuthedUser, db: DbSession) -> list[MethodologyVersionInfo]:
    _known(key)
    rows = (
        await db.execute(
            select(MethodologyVersion).where(MethodologyVersion.key == key).order_by(MethodologyVersion.version.desc())
        )
    ).scalars()
    return [MethodologyVersionInfo(version=r.version, created_at=r.created_at, created_by=r.created_by) for r in rows]


@router.get("/{key}/versions/{v}")
async def get_version(key: str, v: int, user: AuthedUser, db: DbSession) -> MethodologyVersionOut:
    _known(key)
    row = (
        await db.execute(
            select(MethodologyVersion).where(MethodologyVersion.key == key, MethodologyVersion.version == v)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "methodology_not_found")
    return MethodologyVersionOut(
        version=row.version, created_at=row.created_at, created_by=row.created_by, key=row.key, body_md=row.body_md
    )


@router.put("/{key}")
async def update_methodology(key: str, body: MethodologyIn, user: AdminUser, db: DbSession) -> MethodologyOut:
    _known(key)
    try:
        prev = await methodology.current(db, key)
        n = prev.version + 1
    except LookupError:
        n = 1
    row = MethodologyVersion(key=key, version=n, body_md=body.body_md, created_by=user.id)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "methodology_conflict")
    await audit.record(
        db, "methodology.updated", actor_id=user.id, target_type="methodology", target_id=row.id,
        data={"key": key, "version": n},
    )
    await db.refresh(row)
    return _out(row)
