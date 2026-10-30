import re
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunStatus
from app.agents.models import Agent, AgentBinding, AgentProgram
from app.agents.schemas import AdminAgentOut, AgentOut, BindingOut, MachineOut, ProjectAgentOut, RunnerInfo
from app.auth.models import PersonalAccessToken, Role, TokenScope, User
from app.auth.service import now
from app.auth.schemas import UserOut
from app.core.events import Event, publish
from app.projects.access import (
    accessible_project_ids,
    can_manage_project,
    project_team_ids,
)
from app.projects.models import Project, ProjectTeam
from app.runner.registry import BRANCH_CAPABILITY, BRANCH_PROBLEM, WORKFLOW_CAPABILITY, WORKFLOW_PROBLEM, registry
from app.tasks.models import Task
from app.teams.models import TeamMember
from app.teams.service import user_team_ids
from app.workflow.models import TaskWorkflow, WorkflowStatus

PROGRAM_LABELS = {AgentProgram.claude_code: "Claude Code", AgentProgram.codex: "Codex"}

# Windows drive (C:\ or C:/), UNC (\\server\share) or POSIX (/...)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\/]|/)")


def default_agent_name(owner: User, program: AgentProgram) -> str:
    return f"{owner.name}'s {PROGRAM_LABELS[program]}"


def is_absolute_path(path: str) -> bool:
    return bool(_ABSOLUTE_PATH.match(path))


async def agent_statuses(db: AsyncSession, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """online | busy | offline per agent. busy: it has a running run; online: its machine's live runner
    reports it available."""
    ids = set(agent_ids)
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
        if registry.is_available(agent_id)
        else "offline"
        for agent_id in agent_ids
    }


def runner_info(agent_id: uuid.UUID) -> RunnerInfo | None:
    """The live runner of the agent's machine, as its hello said."""
    conn = registry.conn_for_agent(agent_id)
    if conn is None or not conn.version:
        return None
    return RunnerInfo(version=conn.version, os=conn.os or "")


def agent_problems(agent_id: uuid.UUID, owner_id: uuid.UUID, viewer: User) -> list[str]:
    """What its machine's live runner reports as wrong with the agent (shown to the owner and admins only),
    plus the server's own too-old-runner notice (shown to everyone who can see the agent)."""
    conn = registry.conn_for_agent(agent_id)
    if conn is None:
        return []
    private = viewer.id == owner_id or viewer.role == Role.admin
    problems = list(conn.problems.get(agent_id, [])) if private else []
    if WORKFLOW_CAPABILITY not in conn.capabilities:
        problems.append(WORKFLOW_PROBLEM)
    if BRANCH_CAPABILITY not in conn.capabilities:
        problems.append(BRANCH_PROBLEM)
    return problems


async def agent_status(db: AsyncSession, agent_id: uuid.UUID) -> str:
    return (await agent_statuses(db, [agent_id]))[agent_id]


async def has_active_runs(db: AsyncSession, agent_id: uuid.UUID) -> bool:
    """True if the agent has a queued or running run."""
    return (
        await db.scalar(
            select(AgentRun.id).where(AgentRun.agent_id == agent_id, AgentRun.status.in_(ACTIVE_STATUSES)).limit(1)
        )
    ) is not None


async def has_running_runs(db: AsyncSession, agent_id: uuid.UUID) -> bool:
    """True if the agent has a running run: it is at work on its machine right now."""
    return (
        await db.scalar(
            select(AgentRun.id).where(AgentRun.agent_id == agent_id, AgentRun.status == RunStatus.running).limit(1)
        )
    ) is not None


async def check_runner_token(db: AsyncSession, owner_id: uuid.UUID, token_id: uuid.UUID) -> None:
    """An agent may be linked only to its owner's own live runner token."""
    token = await db.get(PersonalAccessToken, token_id)
    if (
        token is None
        or token.user_id != owner_id
        or str(TokenScope.runner) not in token.scopes
        or token.revoked_at is not None
        or (token.expires_at is not None and token.expires_at <= now())
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "runner_token_invalid")


async def unlink_tokens(db: AsyncSession, owner_id: uuid.UUID, token_ids: list[uuid.UUID] | None) -> None:
    """Revoked tokens: their agents become unlinked (None: every token of the owner)."""
    linked = Agent.runner_token_id.in_(token_ids) if token_ids is not None else Agent.runner_token_id.is_not(None)
    agent_ids = (
        await db.execute(
            update(Agent).where(Agent.owner_id == owner_id, linked).values(runner_token_id=None).returning(Agent.id)
        )
    ).scalars().all()
    if not agent_ids:
        return
    projects: set[uuid.UUID] = set()
    for agent_id in agent_ids:
        projects |= await bound_project_ids(db, agent_id)
    await publish_agents_updated(db, owner_id, projects)


async def has_active_workflows(db: AsyncSession, agent_id: uuid.UUID) -> bool:
    """True if a workflow the agent drives is under way (neither idle nor finished)."""
    return (
        await db.scalar(
            select(TaskWorkflow.task_id)
            .where(
                TaskWorkflow.agent_id == agent_id,
                TaskWorkflow.status.not_in((WorkflowStatus.idle, WorkflowStatus.finished)),
            )
            .limit(1)
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


def owner_can_access(project_id: uuid.UUID) -> ColumnElement[bool]:
    """SQL condition on Agent: its owner can access the project (an admin, or in one of its teams).
    A binding whose owner lost access is kept but ignored: not assignable, runnable or listed there."""
    is_admin = select(User.id).where(User.id == Agent.owner_id, User.role == Role.admin).exists()
    is_member = (
        select(ProjectTeam.project_id)
        .join(TeamMember, TeamMember.team_id == ProjectTeam.team_id)
        .where(ProjectTeam.project_id == project_id, TeamMember.user_id == Agent.owner_id)
        .exists()
    )
    return or_(is_admin, is_member)


async def is_usable_binding(db: AsyncSession, agent_id: uuid.UUID, project_id: uuid.UUID) -> bool:
    """The agent is bound to the project and its owner can still access it."""
    found = await db.scalar(
        select(AgentBinding.id)
        .join(Agent, Agent.id == AgentBinding.agent_id)
        .where(AgentBinding.agent_id == agent_id, AgentBinding.project_id == project_id, owner_can_access(project_id))
    )
    return found is not None


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
    token_ids = {a.runner_token_id for a in agents if a.runner_token_id is not None}
    tokens = (
        {t.id: t for t in (await db.execute(select(PersonalAccessToken).where(PersonalAccessToken.id.in_(token_ids)))).scalars()}
        if token_ids
        else {}
    )
    statuses = await agent_statuses(db, list(owner_of))
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
            "problems": agent_problems(a.id, a.owner_id, viewer),
            "bindings": bindings.get(a.id, []),
            "runner": runner_info(a.id),
            "machine": _machine(tokens.get(a.runner_token_id), a.owner_id, viewer),
        }
        for a in agents
    ]


def _machine(token: PersonalAccessToken | None, owner_id: uuid.UUID, viewer: User) -> MachineOut | None:
    if token is None or (viewer.id != owner_id and viewer.role != Role.admin):
        return None
    return MachineOut(
        token_id=token.id, name=token.name, expired=token.expires_at is not None and token.expires_at <= now()
    )


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


def _newest(running: dict, agent_id: uuid.UUID, run: dict) -> None:
    """Keep the most recently started run per agent (a run without a start time counts as oldest)."""
    oldest = datetime.min.replace(tzinfo=UTC)
    current = running.get(agent_id)
    if current is None or (run["started_at"] or oldest) > (current["started_at"] or oldest):
        running[agent_id] = run


async def admin_agents_out(db: AsyncSession, agents: list[Agent], viewer: User) -> list[AdminAgentOut]:
    fields = await _base_fields(db, agents, viewer)
    from app.a2a.models import Question  # local: a2a imports this module

    ids = [a.id for a in agents]
    running: dict = {}
    # ADM-3: what each agent works on now, a task or (§6.6) a question it answers; the newest run wins
    for agent_id, run_id, pkey, num, run_status, started_at in await db.execute(
        select(AgentRun.agent_id, AgentRun.id, Project.key, Task.number, AgentRun.status, AgentRun.started_at)
        .join(Task, Task.id == AgentRun.task_id)
        .join(Project, Project.id == Task.project_id)
        .where(AgentRun.agent_id.in_(ids), AgentRun.status == RunStatus.running)
    ):
        _newest(running, agent_id, {"id": run_id, "kind": "task", "task_key": f"{pkey}-{num}", "status": run_status,
                                    "started_at": started_at})
    for agent_id, run_id, pkey, num, run_status, started_at in await db.execute(
        select(AgentRun.agent_id, AgentRun.id, Project.key, Question.number, AgentRun.status, AgentRun.started_at)
        .join(Question, Question.id == AgentRun.question_id)
        .join(Project, Project.id == Question.target_project_id)
        .where(AgentRun.agent_id.in_(ids), AgentRun.status == RunStatus.running)
    ):
        _newest(running, agent_id, {"id": run_id, "kind": "question", "task_key": f"{pkey}-Q{num}",
                                    "status": run_status, "started_at": started_at})
    return [AdminAgentOut(**f, current_run=running.get(f["id"])) for f in fields]
