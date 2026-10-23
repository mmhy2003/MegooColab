import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunStatus
from app.agents.models import Agent, AgentBinding, AgentProgram
from app.agents.schemas import AdminAgentOut, AgentOut, BindingOut, ProjectAgentOut
from app.auth.models import Role, User
from app.auth.schemas import UserOut
from app.core.events import Event, publish
from app.projects.access import accessible_project_ids, can_manage_project, project_team_ids
from app.projects.models import Project
from app.runner.registry import registry
from app.tasks.models import Task
from app.teams.service import user_team_ids

PROGRAM_LABELS = {AgentProgram.claude_code: "Claude Code", AgentProgram.codex: "Codex"}

# Windows drive (C:\ or C:/), UNC (\\server\share) or POSIX (/...)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\/]|/)")


def default_agent_name(owner: User, program: AgentProgram) -> str:
    return f"{owner.name}'s {PROGRAM_LABELS[program]}"


def is_absolute_path(path: str) -> bool:
    return bool(_ABSOLUTE_PATH.match(path))


async def agent_statuses(db: AsyncSession, agents: list[tuple[uuid.UUID, uuid.UUID]]) -> dict[uuid.UUID, str]:
    """online | busy | offline for (agent_id, owner_id) pairs. busy: it has a running run;
    online: the owner's live runner reports it available."""
    ids = {agent_id for agent_id, _ in agents}
    busy: set[uuid.UUID] = set()
    if ids:
        rows = await db.execute(
            select(AgentRun.agent_id).where(AgentRun.agent_id.in_(ids), AgentRun.status == RunStatus.running)
        )
        busy = set(rows.scalars())
    return {
        agent_id: "busy"
        if agent_id in busy
        else "online"
        if agent_id in registry.available_agents(owner_id)
        else "offline"
        for agent_id, owner_id in agents
    }


async def agent_status(db: AsyncSession, agent_id: uuid.UUID, owner_id: uuid.UUID) -> str:
    return (await agent_statuses(db, [(agent_id, owner_id)]))[agent_id]


async def has_active_runs(db: AsyncSession, agent_id: uuid.UUID) -> bool:
    """True if the agent has a queued or running run."""
    return (
        await db.scalar(
            select(AgentRun.id).where(AgentRun.agent_id == agent_id, AgentRun.status.in_(ACTIVE_STATUSES)).limit(1)
        )
    ) is not None


async def get_owned_agent(db: AsyncSession, user: User, agent_id: uuid.UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent_not_found")
    return agent


def may_use_agent(user: User, agent_owner_id: uuid.UUID, manages: bool) -> bool:
    """AGT-5, the single rule: the owner, an admin, or a manager of the project."""
    return agent_owner_id == user.id or user.role == Role.admin or manages


async def _manages_project(db: AsyncSession, user: User, project: Project) -> bool:
    return can_manage_project(
        user, await project_team_ids(db, project.id), await user_team_ids(db, user.id)
    )


async def can_use_agent(db: AsyncSession, user: User, agent: Agent, project: Project) -> bool:
    return may_use_agent(user, agent.owner_id, await _manages_project(db, user, project))


async def bound_project_ids(db: AsyncSession, agent_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(select(AgentBinding.project_id).where(AgentBinding.agent_id == agent_id))
    return set(rows.scalars())


async def publish_agents_updated(
    db: AsyncSession, owner_id: uuid.UUID, project_ids: set[uuid.UUID]
) -> None:
    for pid in project_ids:
        await publish(db, Event(type="agents.updated", project_id=pid))
    await publish(db, Event(type="agents.updated", user_id=owner_id))


async def _base_fields(db: AsyncSession, agents: list[Agent], viewer: User) -> list[dict]:
    """Common AgentOut fields. Bindings are limited to projects the viewer can see;
    local_path only goes to the owner."""
    if not agents:
        return []
    owners = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_({a.owner_id for a in agents})))
        ).scalars()
    }
    owner_of = {a.id: a.owner_id for a in agents}
    statuses = await agent_statuses(db, list(owner_of.items()))
    allowed = await accessible_project_ids(db, viewer)
    rows = await db.execute(
        select(AgentBinding, Project.key)
        .join(Project, Project.id == AgentBinding.project_id)
        .where(AgentBinding.agent_id.in_(owner_of))
        .order_by(Project.key)
    )
    bindings: dict[uuid.UUID, list[BindingOut]] = {}
    for b, key in rows.all():
        if allowed is not None and b.project_id not in allowed:
            continue
        bindings.setdefault(b.agent_id, []).append(
            BindingOut(
                project_id=b.project_id,
                project_key=key,
                local_path=b.local_path if owner_of[b.agent_id] == viewer.id else None,
            )
        )
    return [
        {
            "id": a.id,
            "name": a.name,
            "program": a.program,
            "answer_mode": a.answer_mode,
            "max_concurrent_runs": a.max_concurrent_runs,
            "owner": UserOut.model_validate(owners[a.owner_id]),
            "status": statuses[a.id],
            "bindings": bindings.get(a.id, []),
        }
        for a in agents
    ]


async def agents_out(db: AsyncSession, agents: list[Agent], viewer: User) -> list[AgentOut]:
    return [AgentOut(**f) for f in await _base_fields(db, agents, viewer)]


async def project_agents_out(
    db: AsyncSession, agents: list[Agent], viewer: User, project: Project
) -> list[ProjectAgentOut]:
    manages = await _manages_project(db, viewer, project)
    fields = await _base_fields(db, agents, viewer)
    return [
        ProjectAgentOut(**f, can_use=may_use_agent(viewer, a.owner_id, manages))
        for f, a in zip(fields, agents, strict=True)
    ]


async def admin_agents_out(db: AsyncSession, agents: list[Agent], viewer: User) -> list[AdminAgentOut]:
    fields = await _base_fields(db, agents, viewer)
    running = {
        agent_id: {"id": run_id, "task_key": f"{pkey}-{num}", "status": run_status, "started_at": started_at}
        for agent_id, run_id, pkey, num, run_status, started_at in await db.execute(
            select(AgentRun.agent_id, AgentRun.id, Project.key, Task.number, AgentRun.status, AgentRun.started_at)
            .join(Task, Task.id == AgentRun.task_id)
            .join(Project, Project.id == Task.project_id)
            .where(AgentRun.agent_id.in_([a.id for a in agents]), AgentRun.status == RunStatus.running)
            .order_by(AgentRun.started_at.desc())
        )
    }
    return [AdminAgentOut(**f, current_run=running.get(f["id"])) for f in fields]
