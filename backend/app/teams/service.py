import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
from app.teams.models import Team, TeamMember


async def user_team_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(select(TeamMember.team_id).where(TeamMember.user_id == user_id))
    return set(rows.scalars())


async def team_member_ids(db: AsyncSession, team_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(select(TeamMember.user_id).where(TeamMember.team_id == team_id))
    return set(rows.scalars())


async def get_team_or_404(db: AsyncSession, team_id: uuid.UUID) -> Team:
    team = await db.get(Team, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return team


async def team_projects(db: AsyncSession, team_id: uuid.UUID) -> list[dict]:
    from app.projects.models import Project, ProjectTeam

    rows = await db.execute(
        select(Project.id, Project.key, Project.name)
        .join(ProjectTeam, ProjectTeam.project_id == Project.id)
        .where(ProjectTeam.team_id == team_id)
        .order_by(Project.name)
    )
    return [{"id": i, "key": k, "name": n} for i, k, n in rows.all()]


async def team_project_counts(db: AsyncSession) -> dict[uuid.UUID, int]:
    from app.projects.models import ProjectTeam

    rows = await db.execute(
        select(ProjectTeam.team_id, func.count()).group_by(ProjectTeam.team_id)
    )
    return dict(rows.all())


async def require_team_manage(db: AsyncSession, user: User, team: Team) -> None:
    """Admins manage every team; managers only teams they belong to."""
    if user.role == Role.admin:
        return
    if user.role == Role.manager and team.id in await user_team_ids(db, user.id):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
