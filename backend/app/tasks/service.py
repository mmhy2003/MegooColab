import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User, UserStatus
from app.projects.access import get_project_for
from app.projects.models import BoardColumn, ColumnCategory, Label, Project, ProjectTeam
from app.projects.schemas import LabelOut
from app.tasks.models import Task, TaskType, task_labels, task_watchers
from app.tasks.schemas import TaskCreate, TaskOut, TaskUpdate
from app.teams.models import TeamMember

KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]{1,9})-(\d+)$")
POSITION_STEP = 1024.0


def _now() -> datetime:
    return datetime.now(UTC)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "task_not_found")


async def get_task_for(
    db: AsyncSession, user: User, key: str, write: bool = False
) -> tuple[Task, Project]:
    m = KEY_RE.match(key)
    if not m:
        raise _not_found()
    project = await get_project_for(db, user, m.group(1), write=write)
    task = (
        await db.execute(
            select(Task).where(Task.project_id == project.id, Task.number == int(m.group(2)))
        )
    ).scalar_one_or_none()
    if task is None:
        raise _not_found()
    return task, project


async def tasks_out(db: AsyncSession, tasks: list[Task]) -> list[TaskOut]:
    if not tasks:
        return []
    ids = [t.id for t in tasks]
    project_keys = dict(
        (await db.execute(select(Project.id, Project.key).where(Project.id.in_({t.project_id for t in tasks})))).all()
    )
    categories = dict(
        (await db.execute(select(BoardColumn.id, BoardColumn.category).where(BoardColumn.id.in_({t.column_id for t in tasks})))).all()
    )
    labels: dict[uuid.UUID, list[LabelOut]] = defaultdict(list)
    for task_id, label in await db.execute(
        select(task_labels.c.task_id, Label)
        .join(Label, Label.id == task_labels.c.label_id)
        .where(task_labels.c.task_id.in_(ids))
        .order_by(Label.name)
    ):
        labels[task_id].append(LabelOut.model_validate(label))
    sub_counts: dict[uuid.UUID, tuple[int, int]] = {}
    child = select(
        Task.parent_id,
        func.count(),
        func.count().filter(BoardColumn.category == ColumnCategory.done),
    ).join(BoardColumn, BoardColumn.id == Task.column_id).where(
        Task.parent_id.in_(ids), Task.type == TaskType.subtask
    ).group_by(Task.parent_id)
    for parent_id, total, done in await db.execute(child):
        sub_counts[parent_id] = (total, done)
    return [
        TaskOut(
            id=t.id,
            key=f"{project_keys[t.project_id]}-{t.number}",
            number=t.number,
            project_id=t.project_id,
            type=t.type,
            title=t.title,
            description_md=t.description_md,
            column_id=t.column_id,
            column_category=categories[t.column_id],
            position=t.position,
            priority=t.priority,
            story_points=t.story_points,
            due_date=t.due_date,
            assignee_user_id=t.assignee_user_id,
            reporter_id=t.reporter_id,
            parent_id=t.parent_id,
            sprint_id=t.sprint_id,
            completed_at=t.completed_at,
            created_at=t.created_at,
            updated_at=t.updated_at,
            labels=labels.get(t.id, []),
            subtask_count=sub_counts.get(t.id, (0, 0))[0],
            subtask_done_count=sub_counts.get(t.id, (0, 0))[1],
        )
        for t in tasks
    ]


async def task_out(db: AsyncSession, task: Task) -> TaskOut:
    await db.flush()
    await db.refresh(task)
    return (await tasks_out(db, [task]))[0]


async def get_column(db: AsyncSession, project: Project, column_id: uuid.UUID) -> BoardColumn:
    col = await db.get(BoardColumn, column_id)
    if col is None or col.project_id != project.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_column")
    return col


async def first_before_column(db: AsyncSession, project: Project) -> BoardColumn:
    return (
        await db.execute(
            select(BoardColumn)
            .where(BoardColumn.project_id == project.id, BoardColumn.category == ColumnCategory.before)
            .order_by(BoardColumn.position)
            .limit(1)
        )
    ).scalar_one()


async def end_position(db: AsyncSession, column_id: uuid.UUID) -> float:
    current = (
        await db.execute(select(func.max(Task.position)).where(Task.column_id == column_id))
    ).scalar_one()
    return (current or 0.0) + POSITION_STEP


def apply_column(task: Task, column: BoardColumn) -> None:
    """Moves the task into the column and keeps completed_at in step with 'done'."""
    task.column_id = column.id
    if column.category == ColumnCategory.done:
        task.completed_at = task.completed_at or _now()
    else:
        task.completed_at = None


async def validate_parent(
    db: AsyncSession,
    project: Project,
    task_type: TaskType,
    parent_id: uuid.UUID | None,
    task_id: uuid.UUID | None = None,
) -> None:
    def invalid() -> HTTPException:
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_parent")

    if task_type == TaskType.epic:
        if parent_id is not None:
            raise invalid()
    elif task_type == TaskType.subtask:
        if parent_id is None:
            raise invalid()
    if parent_id is None:
        return
    parent = await db.get(Task, parent_id)
    if parent is None or parent.project_id != project.id or parent.id == task_id:
        raise invalid()
    if task_type == TaskType.subtask and parent.type in (TaskType.epic, TaskType.subtask):
        raise invalid()
    if task_type in (TaskType.story, TaskType.task, TaskType.bug) and parent.type != TaskType.epic:
        raise invalid()


async def validate_children_after_type_change(db: AsyncSession, task: Task, new_type: TaskType) -> None:
    child_types = set(
        (await db.execute(select(Task.type).where(Task.parent_id == task.id))).scalars()
    )
    if not child_types:
        return
    allowed = {
        TaskType.epic: {TaskType.story, TaskType.task, TaskType.bug},
        TaskType.subtask: set(),
    }.get(new_type, {TaskType.subtask})
    if not child_types <= allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_parent")


async def check_assignee(db: AsyncSession, project: Project, user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    user = await db.get(User, user_id)
    ok = False
    if user is not None and user.status != UserStatus.deactivated:
        if user.role == Role.admin:
            ok = True
        else:
            ok = (
                await db.execute(
                    select(ProjectTeam.project_id)
                    .join(TeamMember, TeamMember.team_id == ProjectTeam.team_id)
                    .where(ProjectTeam.project_id == project.id, TeamMember.user_id == user_id)
                    .limit(1)
                )
            ).first() is not None
    if not ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "assignee_no_access")


async def set_labels(db: AsyncSession, project: Project, task: Task, label_ids: list[uuid.UUID]) -> None:
    wanted = set(label_ids)
    if wanted:
        found = set(
            (await db.execute(select(Label.id).where(Label.id.in_(wanted), Label.project_id == project.id))).scalars()
        )
        if found != wanted:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_label")
    await db.execute(delete(task_labels).where(task_labels.c.task_id == task.id))
    if wanted:
        await db.execute(insert(task_labels), [{"task_id": task.id, "label_id": lid} for lid in wanted])


async def add_watcher(db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> None:
    exists = (
        await db.execute(
            select(task_watchers).where(task_watchers.c.task_id == task_id, task_watchers.c.user_id == user_id)
        )
    ).first()
    if not exists:
        await db.execute(insert(task_watchers).values(task_id=task_id, user_id=user_id))


async def next_number(db: AsyncSession, project: Project) -> int:
    # the row lock taken by UPDATE serializes concurrent creates in the same project
    return (
        await db.execute(
            update(Project)
            .where(Project.id == project.id)
            .values(next_task_number=Project.next_task_number + 1)
            .returning(Project.next_task_number - 1)
        )
    ).scalar_one()


async def create_task(db: AsyncSession, user: User, project: Project, data: TaskCreate) -> Task:
    await validate_parent(db, project, data.type, data.parent_id)
    await check_assignee(db, project, data.assignee_user_id)
    column = (
        await get_column(db, project, data.column_id) if data.column_id else await first_before_column(db, project)
    )
    task = Task(
        project_id=project.id,
        number=await next_number(db, project),
        type=data.type,
        title=data.title,
        description_md=data.description_md,
        position=await end_position(db, column.id),
        priority=data.priority,
        story_points=data.story_points,
        due_date=data.due_date,
        assignee_user_id=data.assignee_user_id,
        reporter_id=user.id,
        parent_id=data.parent_id,
    )
    apply_column(task, column)
    db.add(task)
    await db.flush()
    if data.label_ids:
        await set_labels(db, project, task, data.label_ids)
    await add_watcher(db, task.id, user.id)
    return task


async def update_task(db: AsyncSession, user: User, project: Project, task: Task, data: TaskUpdate) -> Task:
    fields = data.model_fields_set
    new_type = data.type if "type" in fields and data.type is not None else task.type
    new_parent = data.parent_id if "parent_id" in fields else task.parent_id
    if "type" in fields or "parent_id" in fields:
        await validate_parent(db, project, new_type, new_parent, task_id=task.id)
        if new_type != task.type:
            await validate_children_after_type_change(db, task, new_type)
        task.type, task.parent_id = new_type, new_parent
    if "assignee_user_id" in fields:
        await check_assignee(db, project, data.assignee_user_id)
        task.assignee_user_id = data.assignee_user_id
    for name in ("title", "description_md", "priority"):
        if name in fields and getattr(data, name) is not None:
            setattr(task, name, getattr(data, name))
    for name in ("story_points", "due_date"):
        if name in fields:
            setattr(task, name, getattr(data, name))
    if "label_ids" in fields and data.label_ids is not None:
        await set_labels(db, project, task, data.label_ids)
    task.updated_at = _now()
    return task


async def delete_task(db: AsyncSession, task: Task) -> None:
    if task.type == TaskType.epic:
        await db.execute(update(Task).where(Task.parent_id == task.id).values(parent_id=None))
    await db.delete(task)


async def list_tasks(
    db: AsyncSession,
    project: Project,
    *,
    type_: TaskType | None = None,
    assignee: uuid.UUID | None = None,
    label: uuid.UUID | None = None,
    epic: uuid.UUID | None = None,
    sprint: str | None = None,
    column: uuid.UUID | None = None,
    q: str | None = None,
) -> list[Task]:
    stmt = select(Task).where(Task.project_id == project.id).order_by(Task.position, Task.number)
    if type_:
        stmt = stmt.where(Task.type == type_)
    if assignee:
        stmt = stmt.where(Task.assignee_user_id == assignee)
    if label:
        stmt = stmt.where(Task.id.in_(select(task_labels.c.task_id).where(task_labels.c.label_id == label)))
    if epic:
        stmt = stmt.where(Task.parent_id == epic)
    if column:
        stmt = stmt.where(Task.column_id == column)
    if q:
        stmt = stmt.where(Task.title.ilike(f"%{q}%"))
    if sprint == "backlog":
        stmt = stmt.where(Task.sprint_id.is_(None))
    elif sprint:
        try:
            stmt = stmt.where(Task.sprint_id == uuid.UUID(sprint))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_sprint")
    return list((await db.execute(stmt)).scalars())

