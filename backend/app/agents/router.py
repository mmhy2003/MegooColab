import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents import service
from app.agents.models import Agent, AgentBinding
from app.agents.schemas import (
    AdminAgentOut,
    AgentIn,
    AgentOut,
    AgentPatch,
    BindingsIn,
    ProjectAgentOut,
)
from app.audit import service as audit
from app.auth.deps import AdminUser, AuthedUser
from app.core.db import DbSession
from app.projects.access import get_project_for

router = APIRouter(prefix="/api/agents", tags=["agents"])
project_agents_router = APIRouter(prefix="/api/projects", tags=["agents"])
admin_router = APIRouter(prefix="/api/admin/agents", tags=["agents"])


async def _flush_unique_name(db: DbSession) -> None:
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "agent_name_taken")


@router.get("/mine")
async def my_agents(user: AuthedUser, db: DbSession) -> list[AgentOut]:
    rows = (
        await db.execute(select(Agent).where(Agent.owner_id == user.id).order_by(Agent.name))
    ).scalars()
    return await service.agents_out(db, list(rows), user)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(body: AgentIn, user: AuthedUser, db: DbSession) -> AgentOut:
    name = (body.name or "").strip() or service.default_agent_name(user, body.program)
    agent = Agent(
        owner_id=user.id, name=name, program=body.program,
        answer_mode=body.answer_mode, max_concurrent_runs=body.max_concurrent_runs,
    )
    db.add(agent)
    await _flush_unique_name(db)
    await audit.record(
        db, "agent.created", actor_id=user.id, target_type="agent", target_id=agent.id,
        data={"name": agent.name, "program": agent.program},
    )
    await service.publish_agents_updated(db, user.id, set())
    return (await service.agents_out(db, [agent], user))[0]


@router.patch("/{agent_id}")
async def update_agent(agent_id: uuid.UUID, body: AgentPatch, user: AuthedUser, db: DbSession) -> AgentOut:
    agent = await service.get_owned_agent(db, user, agent_id)
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "name_required")
        agent.name = name
    if body.answer_mode is not None:
        agent.answer_mode = body.answer_mode
    if body.max_concurrent_runs is not None:
        agent.max_concurrent_runs = body.max_concurrent_runs
    await _flush_unique_name(db)
    await service.publish_agents_updated(db, user.id, await service.bound_project_ids(db, agent.id))
    return (await service.agents_out(db, [agent], user))[0]


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    agent = await service.get_owned_agent(db, user, agent_id)
    if await service.has_active_runs(db, agent.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "agent_has_active_runs")
    affected = await service.bound_project_ids(db, agent.id)
    await db.delete(agent)
    await audit.record(
        db, "agent.deleted", actor_id=user.id, target_type="agent", target_id=agent.id,
        data={"name": agent.name},
    )
    await service.publish_agents_updated(db, user.id, affected)


@router.put("/{agent_id}/bindings")
async def replace_bindings(
    agent_id: uuid.UUID, body: BindingsIn, user: AuthedUser, db: DbSession
) -> AgentOut:
    agent = await service.get_owned_agent(db, user, agent_id)
    wanted: dict[uuid.UUID, str] = {}
    for item in body.bindings:
        path = item.local_path.strip()
        if not service.is_absolute_path(path):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "local_path_not_absolute")
        try:
            project = await get_project_for(db, user, item.project_ref)
        except HTTPException:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "project_not_accessible")
        wanted[project.id] = path
    existing = {
        b.project_id: b
        for b in (
            await db.execute(select(AgentBinding).where(AgentBinding.agent_id == agent.id))
        ).scalars()
    }
    for pid, b in existing.items():
        if pid not in wanted:
            await db.delete(b)
    for pid, path in wanted.items():
        if pid in existing:
            existing[pid].local_path = path
        else:
            db.add(AgentBinding(agent_id=agent.id, project_id=pid, local_path=path))
    await db.flush()
    await service.publish_agents_updated(db, user.id, set(existing) | set(wanted))
    return (await service.agents_out(db, [agent], user))[0]


@project_agents_router.get("/{ref}/agents")
async def project_agents(ref: str, user: AuthedUser, db: DbSession) -> list[ProjectAgentOut]:
    project = await get_project_for(db, user, ref)
    agents = (
        await db.execute(
            select(Agent)
            .join(AgentBinding, AgentBinding.agent_id == Agent.id)
            .where(AgentBinding.project_id == project.id)
            .order_by(Agent.name)
        )
    ).scalars()
    return await service.project_agents_out(db, list(agents), user, project)


@admin_router.get("")
async def admin_agents(user: AdminUser, db: DbSession) -> list[AdminAgentOut]:
    agents = (await db.execute(select(Agent).order_by(Agent.name))).scalars()
    return await service.admin_agents_out(db, list(agents), user)
