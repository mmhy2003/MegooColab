import uuid
from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.deps import AdminUser
from app.core.db import DbSession

router = APIRouter(prefix="/api/admin/audit", tags=["admin"])


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    data: dict
    created_at: datetime


@router.get("")
async def list_audit(
    admin: AdminUser,
    db: DbSession,
    action: str | None = None,
    actor: uuid.UUID | None = None,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AuditOut]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor:
        stmt = stmt.where(AuditLog.actor_user_id == actor)
    if before:
        stmt = stmt.where(AuditLog.created_at < before)
    return [AuditOut.model_validate(a) for a in (await db.execute(stmt)).scalars()]
