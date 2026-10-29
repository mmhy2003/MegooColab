"""What a dashboard scope covers: a set of projects, and under Mine only the viewer's own tasks and agents."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.auth.models import Role, User
from app.dashboard.schemas import ScopeName
from app.projects.access import accessible_project_ids
from app.projects.models import Project, ProjectStatus, ProjectTeam
from app.tasks.models import Task, TaskType
from app.teams.models import TeamMember

# subtasks are the agent's plan steps and epics group other work: the parent task stands for them
COUNTED_TYPES = (TaskType.task, TaskType.story, TaskType.bug)


@dataclass(frozen=True)
class Scope:
    user: User
    name: ScopeName
    project_ids: frozenset[uuid.UUID] | None  # None: every project
    agent_ids: frozenset[uuid.UUID]  # the viewer's own agents
    tz: tzinfo | None = None  # the viewer's time zone: what "today" means; None: the server's

    def today(self) -> date:
        return today(self.tz)

    def day_start(self, d: date) -> datetime:
        return day_start(d, self.tz)

    def in_projects(self, column) -> ColumnElement[bool]:
        return true() if self.project_ids is None else column.in_(self.project_ids)

    def mine_tasks(self) -> ColumnElement[bool]:
        if self.name != "mine":
            return true()
        return or_(Task.assignee_user_id == self.user.id, Task.assignee_agent_id.in_(self.agent_ids))


def viewer_zone(name: str | None) -> tzinfo | None:
    """The browser's IANA time zone name; an unknown one means the server's."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


async def resolve_scope(db: AsyncSession, user: User, name: ScopeName, tz: tzinfo | None = None) -> Scope:
    admin = user.role == Role.admin
    if name == "all" and not admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    if name == "all":
        project_ids = None
    elif name == "teams" and admin:
        rows = await db.execute(
            select(ProjectTeam.project_id).join(TeamMember, TeamMember.team_id == ProjectTeam.team_id)
            .where(TeamMember.user_id == user.id)
        )
        project_ids = frozenset(rows.scalars())
    else:
        allowed = await accessible_project_ids(db, user)
        project_ids = None if allowed is None else frozenset(allowed)
    # closed (finished, archived) projects are not counted, in any scope
    active = frozenset((await db.execute(select(Project.id).where(Project.status == ProjectStatus.active))).scalars())
    project_ids = active if project_ids is None else project_ids & active
    agent_ids = frozenset((await db.execute(select(Agent.id).where(Agent.owner_id == user.id))).scalars())
    return Scope(user=user, name=name, project_ids=project_ids, agent_ids=agent_ids, tz=tz)


def today(tz: tzinfo | None = None) -> date:
    """Today in `tz`, or in the server's time zone (UTC in the containers)."""
    return datetime.now(tz).date() if tz else datetime.now().astimezone().date()


def day_start(d: date, tz: tzinfo | None = None) -> datetime:
    return datetime.combine(d, time.min, tzinfo=tz) if tz else datetime.combine(d, time.min).astimezone()


def week_end(d: date) -> date:
    """The Sunday that ends d's week."""
    return d + timedelta(days=6 - d.weekday())


def task_link(project_key: str, number: int) -> str:
    return f"/projects/{project_key}/board?task={project_key}-{number}"
