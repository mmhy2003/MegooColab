"""Task figures: the headline task numbers, the viewer's own tasks due this week, tasks finished per day, and the
per-project bars. Each is one aggregate query."""

from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.dashboard.schemas import DayFinished, MyTask, ProjectRow
from app.dashboard.scope import COUNTED_TYPES, Scope, task_link, today, week_end
from app.projects.access import accessible_project_ids
from app.projects.models import BoardColumn, ColumnCategory, Project, ProjectStatus
from app.tasks.models import Task

MY_TASKS = 8
FINISHED_DAYS = 14

_open = BoardColumn.category != ColumnCategory.done
_in_progress = BoardColumn.category.in_((ColumnCategory.working, ColumnCategory.review))


def _count(condition):
    return func.count().filter(condition)


async def task_numbers(db: AsyncSession, scope: Scope) -> dict[str, int]:
    now, overdue = datetime.now(UTC), and_(_open, Task.due_date < scope.today())
    row = (await db.execute(
        select(
            _count(_open).label("open_tasks"),
            _count(_in_progress).label("open_in_progress"),
            _count(Task.completed_at >= now - timedelta(days=7)).label("done_7d"),
            _count(and_(Task.completed_at >= now - timedelta(days=14), Task.completed_at < now - timedelta(days=7)))
            .label("done_prev_7d"),
            _count(overdue).label("overdue"),
            _count(and_(overdue, Task.assignee_user_id == scope.user.id)).label("overdue_mine"),
        )
        .select_from(Task).join(BoardColumn, BoardColumn.id == Task.column_id)
        .where(Task.type.in_(COUNTED_TYPES), scope.in_projects(Task.project_id), scope.mine_tasks())
    )).one()
    return dict(row._mapping)


def due_label(due: date, today_: date) -> Literal["overdue", "today", "week"]:
    return "overdue" if due < today_ else "today" if due == today_ else "week"


async def my_tasks(db: AsyncSession, user: User, tz: tzinfo | None = None) -> list[MyTask]:
    """The viewer's own open tasks that are overdue or due by Sunday, whatever the scope."""
    t = today(tz)
    allowed = await accessible_project_ids(db, user)
    stmt = (
        select(Project.key, Task.number, Task.title, Task.due_date)
        .join(Project, Project.id == Task.project_id).join(BoardColumn, BoardColumn.id == Task.column_id)
        .where(Task.assignee_user_id == user.id, Task.type.in_(COUNTED_TYPES), _open, Task.due_date <= week_end(t),
               Project.status == ProjectStatus.active)
        .order_by(Task.due_date, Project.key, Task.number).limit(MY_TASKS)
    )
    if allowed is not None:
        stmt = stmt.where(Task.project_id.in_(allowed))
    return [
        MyTask(key=f"{key}-{number}", title=title, due_date=due, due=due_label(due, t), link=task_link(key, number))
        for key, number, title, due in (await db.execute(stmt)).all()
    ]


async def finished_daily(db: AsyncSession, scope: Scope) -> list[DayFinished]:
    """Tasks completed on each of the last 14 days, split by whether an agent is (still) assigned."""
    first = scope.today() - timedelta(days=FINISHED_DAYS - 1)
    start = scope.day_start(first)
    day = func.floor((func.extract("epoch", Task.completed_at) - start.timestamp()) / 86400).label("day")
    by_agent = Task.assignee_agent_id.is_not(None)
    rows = await db.execute(
        select(day, _count(by_agent), _count(~by_agent))
        .where(Task.completed_at >= start, Task.type.in_(COUNTED_TYPES), scope.in_projects(Task.project_id),
               scope.mine_tasks())
        .group_by(day)
    )
    counts = {int(d): (agents, people) for d, agents, people in rows.all()}
    return [
        DayFinished(day=first + timedelta(days=i), agents=counts.get(i, (0, 0))[0], people=counts.get(i, (0, 0))[1])
        for i in range(FINISHED_DAYS)
    ]


async def projects(db: AsyncSession, scope: Scope) -> list[ProjectRow]:
    counted = and_(Task.project_id == Project.id, Task.type.in_(COUNTED_TYPES), scope.mine_tasks())
    rows = await db.execute(
        select(
            Project.key, Project.name,
            _count(_open), _count(_in_progress), _count(BoardColumn.category == ColumnCategory.done),
            _count(and_(_open, Task.due_date < scope.today())),
        )
        .select_from(Project)
        .outerjoin(Task, counted).outerjoin(BoardColumn, BoardColumn.id == Task.column_id)
        .where(scope.in_projects(Project.id))
        .group_by(Project.id).order_by(Project.key)
    )
    return [
        ProjectRow(key=key, name=name, open=open_, in_progress=working, done=done, late=late)
        for key, name, open_, working, done, late in rows.all()
    ]
