import uuid
from collections import Counter

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
from app.projects.access import project_team_ids
from app.projects.models import (
    DEFAULT_COLUMNS,
    BoardColumn,
    ColumnCategory,
    Project,
    ProjectTeam,
)
from app.projects.schemas import ColumnOut, ProjectOut
from app.teams.models import Team
from app.teams.service import user_team_ids

REQUIRED_CATEGORIES = (ColumnCategory.before, ColumnCategory.done)


async def project_out(db: AsyncSession, project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        key=project.key,
        name=project.name,
        description=project.description,
        sprints_enabled=project.sprints_enabled,
        finishing_option=project.finishing_option,
        require_human_code_review=project.require_human_code_review,
        commit_docs_to_repo=project.commit_docs_to_repo,
        team_ids=sorted(await project_team_ids(db, project.id)),
        status=project.status,
        created_at=project.created_at,
    )


async def check_team_ids(db: AsyncSession, user: User, team_ids: set[uuid.UUID]) -> None:
    """All teams must exist; managers may only attach teams they belong to."""
    found = set((await db.execute(select(Team.id).where(Team.id.in_(team_ids)))).scalars())
    if found != team_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_team")
    if user.role != Role.admin and not team_ids <= await user_team_ids(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "team_not_yours")


async def set_project_teams(db: AsyncSession, project: Project, team_ids: set[uuid.UUID]) -> None:
    await db.execute(delete(ProjectTeam).where(ProjectTeam.project_id == project.id))
    for tid in team_ids:
        db.add(ProjectTeam(project_id=project.id, team_id=tid))


async def create_default_columns(db: AsyncSession, project: Project) -> None:
    for i, (name, category) in enumerate(DEFAULT_COLUMNS):
        db.add(BoardColumn(project_id=project.id, name=name, position=i, category=category))


async def list_columns(db: AsyncSession, project_id: uuid.UUID) -> list[BoardColumn]:
    rows = await db.execute(
        select(BoardColumn).where(BoardColumn.project_id == project_id).order_by(BoardColumn.position)
    )
    return list(rows.scalars())


async def column_task_counts(db: AsyncSession, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
    from app.tasks.models import Task

    rows = await db.execute(
        select(Task.column_id, func.count()).where(Task.project_id == project_id).group_by(Task.column_id)
    )
    return dict(rows.all())


async def columns_out(db: AsyncSession, project_id: uuid.UUID) -> list[ColumnOut]:
    counts = await column_task_counts(db, project_id)
    return [
        ColumnOut(id=c.id, name=c.name, position=c.position, category=c.category, task_count=counts.get(c.id, 0))
        for c in await list_columns(db, project_id)
    ]


def ensure_required_categories(categories: list[ColumnCategory]) -> None:
    present = Counter(categories)
    if any(present[c] == 0 for c in REQUIRED_CATEGORIES):
        raise HTTPException(status.HTTP_409_CONFLICT, "last_before_or_done_column")


async def get_column_or_404(db: AsyncSession, project: Project, column_id: uuid.UUID) -> BoardColumn:
    col = await db.get(BoardColumn, column_id)
    if col is None or col.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "column_not_found")
    return col


async def move_column_tasks(
    db: AsyncSession, project: Project, column: BoardColumn, move_to: uuid.UUID | None
) -> None:
    """Before a column is deleted, its tasks go to `move_to` (required when there are any)."""
    from app.tasks.models import Task
    from app.tasks.service import POSITION_STEP, apply_column, end_position

    tasks = list(
        (await db.execute(select(Task).where(Task.column_id == column.id).order_by(Task.position))).scalars()
    )
    if not tasks:
        return
    if move_to is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "move_to_required")
    target = await db.get(BoardColumn, move_to)
    if target is None or target.project_id != project.id or target.id == column.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_move_to")
    pos = await end_position(db, target.id)
    for t in tasks:
        apply_column(t, target)
        t.position = pos
        pos += POSITION_STEP
    await db.flush()
