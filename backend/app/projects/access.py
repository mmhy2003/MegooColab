import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
from app.projects.models import Project, ProjectStatus, ProjectTeam
from app.teams.models import TeamMember


async def accessible_project_ids(db: AsyncSession, user: User) -> set[uuid.UUID] | None:
    """Project ids the user can see; None means every project (admins)."""
    if user.role == Role.admin:
        return None
    rows = await db.execute(
        select(ProjectTeam.project_id)
        .join(TeamMember, TeamMember.team_id == ProjectTeam.team_id)
        .where(TeamMember.user_id == user.id)
    )
    return set(rows.scalars())


async def project_team_ids(db: AsyncSession, project_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(select(ProjectTeam.team_id).where(ProjectTeam.project_id == project_id))
    return set(rows.scalars())


def _parse_ref(project_ref: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(project_ref)
    except ValueError:
        return None


async def get_project_for(
    db: AsyncSession, user: User, project_ref: str, write: bool = False
) -> Project:
    pid = _parse_ref(project_ref)
    stmt = select(Project).where(
        Project.id == pid if pid else Project.key == project_ref.upper()
    )
    project = (await db.execute(stmt)).scalar_one_or_none()
    allowed = await accessible_project_ids(db, user)
    if project is None or (allowed is not None and project.id not in allowed):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project_not_found")
    if write and user.role == Role.viewer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    if write and project.status != ProjectStatus.active:
        # finished and archived projects are read-only; the status and delete routes load the project without write
        raise HTTPException(status.HTTP_409_CONFLICT, "project_closed")
    return project


def can_manage_project(
    user: User, project_team_ids_: set[uuid.UUID], user_team_ids: set[uuid.UUID]
) -> bool:
    if user.role == Role.admin:
        return True
    return user.role == Role.manager and bool(project_team_ids_ & user_team_ids)


async def require_manage(db: AsyncSession, user: User, project: Project) -> None:
    from app.teams.service import user_team_ids

    if not can_manage_project(
        user, await project_team_ids(db, project.id), await user_team_ids(db, user.id)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
