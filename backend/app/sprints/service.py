import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.models import BoardColumn, ColumnCategory, Project
from app.sprints.models import Sprint, SprintSnapshot, SprintState
from app.sprints.schemas import BurndownPoint
from app.tasks.models import Task, TaskType

SPRINTABLE = (TaskType.story, TaskType.task, TaskType.bug)


def today() -> date:
    return datetime.now(UTC).date()


def require_sprints(project: Project) -> None:
    if not project.sprints_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "sprints_disabled")


async def get_sprint(db: AsyncSession, sprint_id: uuid.UUID) -> Sprint:
    sprint = await db.get(Sprint, sprint_id)
    if sprint is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sprint_not_found")
    return sprint


async def points(db: AsyncSession, sprint_id: uuid.UUID) -> tuple[int, int]:
    """(total, remaining) story points of the sprint's sprintable tasks."""
    pts = func.coalesce(func.sum(func.coalesce(Task.story_points, 0)), 0)
    base = (
        select(pts)
        .join(BoardColumn, BoardColumn.id == Task.column_id)
        .where(Task.sprint_id == sprint_id, Task.type.in_(SPRINTABLE))
    )
    total = (await db.execute(base)).scalar_one()
    remaining = (await db.execute(base.where(BoardColumn.category != ColumnCategory.done))).scalar_one()
    return int(total), int(remaining)


async def record_snapshot(db: AsyncSession, sprint_id: uuid.UUID) -> None:
    await db.flush()
    total, remaining = await points(db, sprint_id)
    stmt = insert(SprintSnapshot).values(
        id=uuid.uuid4(), sprint_id=sprint_id, day=today(), total_points=total, remaining_points=remaining
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["sprint_id", "day"],
            set_={"total_points": total, "remaining_points": remaining},
        )
    )


async def snapshot_if_active(db: AsyncSession, sprint_id: uuid.UUID | None) -> None:
    if sprint_id is None:
        return
    sprint = await db.get(Sprint, sprint_id)
    if sprint is not None and sprint.state == SprintState.active:
        await record_snapshot(db, sprint.id)


async def start(db: AsyncSession, sprint: Sprint) -> None:
    if sprint.state != SprintState.planned:
        raise HTTPException(status.HTTP_409_CONFLICT, "sprint_not_planned")
    active = (
        await db.execute(
            select(Sprint.id).where(Sprint.project_id == sprint.project_id, Sprint.state == SprintState.active)
        )
    ).first()
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, "active_sprint_exists")
    sprint.state = SprintState.active
    total, _ = await points(db, sprint.id)
    sprint.committed_points = total
    await record_snapshot(db, sprint.id)


async def complete(db: AsyncSession, sprint: Sprint, move_open_to: str | uuid.UUID) -> None:
    if sprint.state != SprintState.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "sprint_not_active")
    target: uuid.UUID | None = None
    if move_open_to != "backlog":
        nxt = await db.get(Sprint, move_open_to)
        if nxt is None or nxt.project_id != sprint.project_id or nxt.state != SprintState.planned:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_target_sprint")
        target = nxt.id
    await record_snapshot(db, sprint.id)
    total, remaining = await points(db, sprint.id)
    sprint.completed_points = total - remaining
    sprint.state = SprintState.completed
    sprint.completed_at = datetime.now(UTC)
    open_ids = select(Task.id).join(BoardColumn, BoardColumn.id == Task.column_id).where(
        Task.sprint_id == sprint.id, BoardColumn.category != ColumnCategory.done
    )
    await db.execute(update(Task).where(Task.id.in_(open_ids)).values(sprint_id=target))


async def burndown(db: AsyncSession, sprint: Sprint) -> list[BurndownPoint]:
    last_day = min(today(), sprint.end_date)
    if sprint.state == SprintState.planned or last_day < sprint.start_date:
        return []
    snaps = dict(
        (await db.execute(
            select(SprintSnapshot.day, SprintSnapshot.remaining_points).where(SprintSnapshot.sprint_id == sprint.id)
        )).all()
    )
    committed = sprint.committed_points or 0
    span = max((sprint.end_date - sprint.start_date).days, 1)
    out: list[BurndownPoint] = []
    remaining = committed
    day = sprint.start_date
    while day <= last_day:
        remaining = snaps.get(day, remaining)
        ideal = committed * (1 - (day - sprint.start_date).days / span)
        out.append(BurndownPoint(day=day, remaining_points=remaining, ideal_points=round(ideal, 2)))
        day += timedelta(days=1)
    return out
