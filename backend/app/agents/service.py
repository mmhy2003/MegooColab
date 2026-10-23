import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentBinding, AgentProgram
from app.agents.schemas import AdminAgentOut, AgentOut, BindingOut, ProjectAgentOut
from app.auth.models import Role, User
from app.auth.schemas import UserOut
from app.core.events import Event, publish
from app.projects.access import accessible_project_ids, can_manage_project, project_team_ids
from app.projects.models import Project
from app.teams.service import user_team_ids

PROGRAM_LABELS = {AgentProgram.claude_code: "Claude Code", AgentProgram.codex: "Codex"}

# Windows drive (C:\ or C:/), UNC (\\server\share) or POSIX (/...)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\/]|/)")


def default_agent_name(owner: User, program: AgentProgram) -> str:
    return f"{owner.name}'s {PROGRAM_LABELS[program]}"


def is_absolute_path(path: str) -> bool:
    return bool(_ABSOLUTE_PATH.match(path))


def agent_status(agent_id: uuid.UUID) -> str:
    """online | busy | offline. Task 4 adds the runner registry, Task 5 adds busy."""
    return "offline"


async def has_active_runs(db: AsyncSession, agent_id: uuid.UUID) -> bool:
    """True if the agent has a queued or running run. Task 5 implements this."""
    return False


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
            "status": agent_status(a.id),
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
    """current_run stays null until Task 5 adds runs."""
    return [AdminAgentOut(**f) for f in await _base_fields(db, agents, viewer)]
