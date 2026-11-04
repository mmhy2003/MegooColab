import uuid

from fastapi import APIRouter, Response, status

from sqlalchemy import select

from app.agents.models import Agent, AgentBinding
from app.agents.service import owner_can_access
from app.auth.deps import AuthedUser
from app.images.support import runner_has
from app.runner.registry import SECRETS_CAPABILITY
from app.core.db import DbSession
from app.projects.access import get_project_for, require_manage
from app.secrets import service
from app.secrets.schemas import OutdatedAgent, SecretIn, SecretOut, SecretPatch, SecretValueIn

router = APIRouter(tags=["secrets"])


# -- personal -----------------------------------------------------------------------------------------


@router.get("/api/secrets")
async def my_secrets(user: AuthedUser, db: DbSession) -> list[SecretOut]:
    return await service.list_secrets(db, user_id=user.id)


@router.get("/api/secrets/outdated-agents")
async def outdated_agents(user: AuthedUser, db: DbSession, project: str | None = None) -> list[OutdatedAgent]:
    """The caller's own agents (or, with `project`, the project's agents) whose runner can't take secrets: an offline
    machine counts by its last hello."""
    if project:
        p = await get_project_for(db, user, project)
        stmt = (select(Agent).join(AgentBinding, AgentBinding.agent_id == Agent.id)
                .where(AgentBinding.project_id == p.id, owner_can_access(p.id)))
    else:
        stmt = select(Agent).where(Agent.owner_id == user.id)
    agents = (await db.execute(stmt.order_by(Agent.name))).scalars().unique().all()
    return [OutdatedAgent(id=a.id, name=a.name) for a in agents if not await runner_has(db, a, SECRETS_CAPABILITY)]


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
    # a finished or archived project's credentials can still be removed
    project = await get_project_for(db, user, ref)
    await require_manage(db, user, project)
    await service.delete(db, user, await service.get_secret(db, secret_id, project_id=project.id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
