"""Personal and project secrets: write-only values, encrypted, every change audited by name (never by value)."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth.models import User
from app.core.crypto import encrypt
from app.kb.schemas import Named
from app.projects.models import Project
from app.secrets.models import Secret
from app.secrets.names import check_name
from app.secrets.schemas import SecretIn, SecretOut, SecretPatch


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "secret_not_found")


async def secret_out(db: AsyncSession, s: Secret) -> SecretOut:
    by = await db.get(User, s.updated_by) if s.updated_by else None
    return SecretOut(id=s.id, name=s.name, description=s.description, updated_at=s.updated_at,
                     value_updated_at=s.value_updated_at,
                     updated_by=Named(id=by.id, name=by.name) if by else None)


async def list_secrets(db: AsyncSession, *, user_id: uuid.UUID | None = None,
                       project_id: uuid.UUID | None = None) -> list[SecretOut]:
    owner = Secret.user_id == user_id if user_id is not None else Secret.project_id == project_id
    rows = (await db.execute(select(Secret).where(owner).order_by(Secret.name))).scalars().all()
    return [await secret_out(db, s) for s in rows]


async def get_secret(db: AsyncSession, secret_id: uuid.UUID, *, user_id: uuid.UUID | None = None,
                     project_id: uuid.UUID | None = None) -> Secret:
    s = await db.get(Secret, secret_id)
    if s is None or (user_id is not None and s.user_id != user_id) or (
        project_id is not None and s.project_id != project_id
    ):
        raise _not_found()
    return s


def _audit_data(s: Secret) -> dict:
    data = {"name": s.name, "scope": "project" if s.project_id else "user"}
    if s.project_id:
        data["project_id"] = str(s.project_id)
    return data


async def _flush(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "secret_name_taken") from None


async def create(db: AsyncSession, actor: User, data: SecretIn, *, user_id: uuid.UUID | None = None,
                 project: Project | None = None) -> Secret:
    check_name(data.name)
    s = Secret(id=uuid.uuid4(), user_id=user_id, project_id=project.id if project else None, name=data.name,
               description=data.description.strip(), value_enc=encrypt(data.value), updated_by=actor.id)
    db.add(s)
    await _flush(db)
    await audit.record(db, "secret.created", actor_id=actor.id, target_type="secret", target_id=s.id,
                       data=_audit_data(s))
    return s


async def update(db: AsyncSession, actor: User, s: Secret, data: SecretPatch) -> Secret:
    if data.name is not None:
        check_name(data.name)
        s.name = data.name
    if data.description is not None:
        s.description = data.description.strip()
    s.updated_by = actor.id
    s.updated_at = func.now()
    await _flush(db)
    await audit.record(db, "secret.updated", actor_id=actor.id, target_type="secret", target_id=s.id,
                       data=_audit_data(s))
    await db.refresh(s)
    return s


async def replace_value(db: AsyncSession, actor: User, s: Secret, value: str) -> Secret:
    s.value_enc = encrypt(value)
    s.updated_by = actor.id
    s.updated_at = s.value_updated_at = func.now()
    await db.flush()
    await audit.record(db, "secret.value_replaced", actor_id=actor.id, target_type="secret", target_id=s.id,
                       data=_audit_data(s))
    await db.refresh(s)
    return s


async def delete(db: AsyncSession, actor: User, s: Secret) -> None:
    await audit.record(db, "secret.deleted", actor_id=actor.id, target_type="secret", target_id=s.id,
                       data=_audit_data(s))
    await db.delete(s)
    await db.flush()
