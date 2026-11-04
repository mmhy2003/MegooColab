import uuid

from fastapi import APIRouter, Response, status

from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.projects.access import get_project_for, require_manage
from app.secrets import service
from app.secrets.schemas import SecretIn, SecretOut, SecretPatch, SecretValueIn

router = APIRouter(tags=["secrets"])


# -- personal -----------------------------------------------------------------------------------------


@router.get("/api/secrets")
async def my_secrets(user: AuthedUser, db: DbSession) -> list[SecretOut]:
    return await service.list_secrets(db, user_id=user.id)


@router.post("/api/secrets", status_code=status.HTTP_201_CREATED)
async def add_my_secret(body: SecretIn, user: AuthedUser, db: DbSession) -> SecretOut:
    s = await service.create(db, user, body, user_id=user.id)
    await db.commit()
    return await service.secret_out(db, s)


@router.patch("/api/secrets/{secret_id}")
async def edit_my_secret(secret_id: uuid.UUID, body: SecretPatch, user: AuthedUser, db: DbSession) -> SecretOut:
    s = await service.update(db, user, await service.get_secret(db, secret_id, user_id=user.id), body)
    await db.commit()
    return await service.secret_out(db, s)


@router.put("/api/secrets/{secret_id}/value")
async def replace_my_value(secret_id: uuid.UUID, body: SecretValueIn, user: AuthedUser, db: DbSession) -> SecretOut:
    s = await service.replace_value(db, user, await service.get_secret(db, secret_id, user_id=user.id), body.value)
    await db.commit()
    return await service.secret_out(db, s)


@router.delete("/api/secrets/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_secret(secret_id: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    await service.delete(db, user, await service.get_secret(db, secret_id, user_id=user.id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- a project's: its members read, its managers and admins write ------------------------------------


async def _managed(db, user, ref: str):
    project = await get_project_for(db, user, ref, write=True)
    await require_manage(db, user, project)
    return project


@router.get("/api/projects/{ref}/secrets")
async def project_secrets(ref: str, user: AuthedUser, db: DbSession) -> list[SecretOut]:
    project = await get_project_for(db, user, ref)
    return await service.list_secrets(db, project_id=project.id)


@router.post("/api/projects/{ref}/secrets", status_code=status.HTTP_201_CREATED)
async def add_project_secret(ref: str, body: SecretIn, user: AuthedUser, db: DbSession) -> SecretOut:
    project = await _managed(db, user, ref)
    s = await service.create(db, user, body, project=project)
    await db.commit()
    return await service.secret_out(db, s)


@router.patch("/api/projects/{ref}/secrets/{secret_id}")
async def edit_project_secret(ref: str, secret_id: uuid.UUID, body: SecretPatch, user: AuthedUser,
                              db: DbSession) -> SecretOut:
    project = await _managed(db, user, ref)
    s = await service.update(db, user, await service.get_secret(db, secret_id, project_id=project.id), body)
    await db.commit()
    return await service.secret_out(db, s)


@router.put("/api/projects/{ref}/secrets/{secret_id}/value")
async def replace_project_value(ref: str, secret_id: uuid.UUID, body: SecretValueIn, user: AuthedUser,
                                db: DbSession) -> SecretOut:
    project = await _managed(db, user, ref)
    s = await service.get_secret(db, secret_id, project_id=project.id)
    s = await service.replace_value(db, user, s, body.value)
    await db.commit()
    return await service.secret_out(db, s)


@router.delete("/api/projects/{ref}/secrets/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_secret(ref: str, secret_id: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    project = await _managed(db, user, ref)
    await service.delete(db, user, await service.get_secret(db, secret_id, project_id=project.id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
