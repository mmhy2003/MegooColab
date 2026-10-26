import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.agents.service import agent_statuses, can_use_agent, is_usable_binding
from app.auth.models import Role, User, UserStatus
from app.core.events import Event, publish
from app.projects.access import can_manage_project, get_project_for
from app.projects.models import BoardColumn, ColumnCategory, Label, Project, ProjectTeam
from app.projects.schemas import LabelOut
from app.sprints.service import snapshot_if_active
from app.tasks import ordering
from app.tasks.models import (
    LinkKind,
    Task,
    TaskEvent,
    TaskLink,
    TaskType,
    task_labels,
    task_watchers,
)
from app.tasks.schemas import (
    AssigneeAgentOut,
    LinkedTask,
    MoveIn,
    TaskCreate,
    TaskLinkOut,
    TaskOut,
    TaskUpdate,
)
from app.teams.models import TeamMember
from app.teams.service import user_team_ids
from app.workflow.models import DocKind, DocStatus, TaskWorkflow, WorkflowDocument
from app.workflow.rules import can_act
from app.workflow.schemas import TaskWorkflowOut

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


async def task_changed(db: AsyncSession, task: Task, kind: str = "task.updated") -> None:
    """Tells live boards about a task change (and keeps an active sprint's burndown current)."""
    await publish(db, Event(type=kind, project_id=task.project_id, task_id=task.id))
    if kind != "task.deleted":
        await snapshot_if_active(db, task.sprint_id)


async def tasks_out(db: AsyncSession, tasks: list[Task], viewer: User) -> list[TaskOut]:
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
    watchers: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for task_id, user_id in await db.execute(
        select(task_watchers.c.task_id, task_watchers.c.user_id).where(task_watchers.c.task_id.in_(ids))
    ):
        watchers[task_id].append(user_id)
    links = await _links_for(db, ids)
    workflows = await _workflows_for(db, tasks, viewer)
    agent_ids = {t.assignee_agent_id for t in tasks if t.assignee_agent_id}
    agents: dict[uuid.UUID, AssigneeAgentOut] = {}
    if agent_ids:
        rows = list((await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))).scalars())
        statuses = await agent_statuses(db, [(a.id, a.owner_id) for a in rows])
        for a in rows:
            agents[a.id] = AssigneeAgentOut(
                id=a.id, name=a.name, program=a.program, owner_id=a.owner_id, status=statuses[a.id]
            )
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
            assignee_agent_id=t.assignee_agent_id,
            assignee_agent=agents.get(t.assignee_agent_id) if t.assignee_agent_id else None,
            reporter_id=t.reporter_id,
            parent_id=t.parent_id,
            sprint_id=t.sprint_id,
            completed_at=t.completed_at,
            created_at=t.created_at,
            updated_at=t.updated_at,
            labels=labels.get(t.id, []),
            subtask_count=sub_counts.get(t.id, (0, 0))[0],
            subtask_done_count=sub_counts.get(t.id, (0, 0))[1],
            links=links.get(t.id, []),
            watcher_ids=watchers.get(t.id, []),
            workflow=workflows.get(t.id),
        )
        for t in tasks
    ]


async def _workflows_for(
    db: AsyncSession, tasks: list[Task], viewer: User
) -> dict[uuid.UUID, TaskWorkflowOut]:
    """One query for every task workflow; steps_total is the step count of the latest approved plan.
    can_act is the engine's WF-6 rule for the viewer, evaluated in bulk."""
    ids = [t.id for t in tasks]
    plan_steps = (
        select(func.jsonb_array_length(WorkflowDocument.steps))
        .where(
            WorkflowDocument.task_id == TaskWorkflow.task_id,
            WorkflowDocument.kind == DocKind.plan,
            WorkflowDocument.status == DocStatus.approved,
        )
        .order_by(WorkflowDocument.version.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = list(await db.execute(select(TaskWorkflow, plan_steps).where(TaskWorkflow.task_id.in_(ids))))
    by_task = {t.id: t for t in tasks}
    owners: dict[uuid.UUID, uuid.UUID] = {}
    manages: dict[uuid.UUID, bool] = {}
    if rows:
        agent_ids = {by_task[wf.task_id].assignee_agent_id or wf.agent_id for wf, _ in rows} - {None}
        if agent_ids:
            owners = dict((await db.execute(select(Agent.id, Agent.owner_id).where(Agent.id.in_(agent_ids)))).all())
        my_teams = await user_team_ids(db, viewer.id)
        project_teams: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for project_id, team_id in await db.execute(
            select(ProjectTeam.project_id, ProjectTeam.team_id).where(
                ProjectTeam.project_id.in_({t.project_id for t in tasks})
            )
        ):
            project_teams[project_id].add(team_id)
        for project_id in {t.project_id for t in tasks}:
            manages[project_id] = can_manage_project(viewer, project_teams[project_id], my_teams)

    def viewer_can_act(wf: TaskWorkflow) -> bool:
        task = by_task[wf.task_id]
        return can_act(
            viewer, task, wf, manages.get(task.project_id, False), owners.get(task.assignee_agent_id or wf.agent_id)
        )

    return {
        wf.task_id: TaskWorkflowOut(
            driver=wf.driver,
            stage=wf.stage,
            status=wf.status,
            needs=wf.needs,
            enforcement=wf.enforcement,
            current_step=wf.current_step,
            steps_total=total,
            escalation_reason=wf.escalation_reason,
            can_act=viewer_can_act(wf),
        )
        for wf, total in rows
    }


async def _links_for(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[TaskLinkOut]]:
    rows = list(
        (await db.execute(
            select(TaskLink).where((TaskLink.source_id.in_(ids)) | (TaskLink.target_id.in_(ids)))
        )).scalars()
    )
    if not rows:
        return {}
    other_ids = {r.source_id for r in rows} | {r.target_id for r in rows}
    info = {
        tid: LinkedTask(key=f"{pkey}-{num}", title=title, column_category=cat)
        for tid, pkey, num, title, cat in await db.execute(
            select(Task.id, Project.key, Task.number, Task.title, BoardColumn.category)
            .join(Project, Project.id == Task.project_id)
            .join(BoardColumn, BoardColumn.id == Task.column_id)
            .where(Task.id.in_(other_ids))
        )
    }
    out: dict[uuid.UUID, list[TaskLinkOut]] = defaultdict(list)
    wanted = set(ids)
    for r in rows:
        if r.source_id in wanted:
            out[r.source_id].append(TaskLinkOut(id=r.id, kind=str(r.kind), task=info[r.target_id]))
        if r.target_id in wanted:
            kind = "blocked_by" if r.kind == LinkKind.blocks else "relates"
            out[r.target_id].append(TaskLinkOut(id=r.id, kind=kind, task=info[r.source_id]))
    return out


async def task_out(db: AsyncSession, task: Task, viewer: User) -> TaskOut:
    await db.flush()
    await db.refresh(task)
    return (await tasks_out(db, [task], viewer))[0]


async def record_event(
    db: AsyncSession, task: Task, actor_id: uuid.UUID | None, kind: str, data: dict | None = None
) -> TaskEvent:
    event = TaskEvent(task_id=task.id, actor_user_id=actor_id, kind=kind, data=data or {})
    db.add(event)
    return event


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

    if (task_type == TaskType.epic and parent_id is not None) or (task_type == TaskType.subtask and parent_id is None):
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


async def check_agent_assignee(
    db: AsyncSession, user: User, project: Project, agent_id: uuid.UUID | None
) -> None:
    """Order matters: unknown agent 422, not bound to the project 422, not allowed to use it 403."""
    if agent_id is None:
        return
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_agent")
    if not await is_usable_binding(db, agent_id, project.id):  # also when its owner lost access
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_not_bound")
    if not await can_use_agent(db, user, agent, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot_use_agent")


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
    if data.assignee_user_id and data.assignee_agent_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "single_assignee")
    await check_assignee(db, project, data.assignee_user_id)
    await check_agent_assignee(db, user, project, data.assignee_agent_id)
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
        assignee_agent_id=data.assignee_agent_id,
        reporter_id=user.id,
        parent_id=data.parent_id,
    )
    apply_column(task, column)
    db.add(task)
    await db.flush()
    if data.label_ids:
        await set_labels(db, project, task, data.label_ids)
    await add_watcher(db, task.id, user.id)
    await record_event(db, task, user.id, "created", {"column": str(column.id)})
    # local: memory imports the task modules
    from app.memory.sources import queue_extract

    await queue_extract(db, "task", task.id)
    return task


TRACKED_FIELDS = ("type", "parent_id", "title", "description_md", "priority", "story_points", "due_date")


def _jsonable(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


async def update_task(db: AsyncSession, user: User, project: Project, task: Task, data: TaskUpdate) -> Task:
    fields = data.model_fields_set
    before = {name: getattr(task, name) for name in TRACKED_FIELDS}
    new_type = data.type if "type" in fields and data.type is not None else task.type
    new_parent = data.parent_id if "parent_id" in fields else task.parent_id
    if "type" in fields or "parent_id" in fields:
        await validate_parent(db, project, new_type, new_parent, task_id=task.id)
        if new_type != task.type:
            # imported here: the workflow engine imports this module
            from app.workflow import board

            await board.before_type_change(db, task, new_type)
            await validate_children_after_type_change(db, task, new_type)
        task.type, task.parent_id = new_type, new_parent
    if "assignee_user_id" in fields or "assignee_agent_id" in fields:
        new_user, new_agent = task.assignee_user_id, task.assignee_agent_id
        if "assignee_user_id" in fields:
            new_user = data.assignee_user_id
            new_agent = None if new_user else new_agent
        if "assignee_agent_id" in fields:
            if new_user and data.assignee_agent_id and "assignee_user_id" in fields:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "single_assignee")
            new_agent = data.assignee_agent_id
            new_user = None if new_agent else new_user
        if (new_user, new_agent) != (task.assignee_user_id, task.assignee_agent_id):
            # imported here: the workflow engine imports this module
            from app.workflow import board

            await board.before_reassign(db, task, new_agent, new_user)
            if new_user != task.assignee_user_id:
                await check_assignee(db, project, new_user)
            if new_agent != task.assignee_agent_id:
                await check_agent_assignee(db, user, project, new_agent)
            await record_event(db, task, user.id, "assigned", {
                "from": _jsonable(task.assignee_user_id), "to": _jsonable(new_user),
                "to_agent": _jsonable(new_agent)})
            task.assignee_user_id, task.assignee_agent_id = new_user, new_agent
    for name in ("title", "description_md", "priority"):
        if name in fields and getattr(data, name) is not None:
            setattr(task, name, getattr(data, name))
    for name in ("story_points", "due_date"):
        if name in fields:
            setattr(task, name, getattr(data, name))
    if "label_ids" in fields and data.label_ids is not None:
        await set_labels(db, project, task, data.label_ids)
        await record_event(db, task, user.id, "field_changed", {"field": "labels"})
    for name, old in before.items():
        new = getattr(task, name)
        if new != old:
            change = {"field": name}
            if name != "description_md":
                change |= {"from": _jsonable(old), "to": _jsonable(new)}
            await record_event(db, task, user.id, "field_changed", change)
    if before["title"] != task.title or before["description_md"] != task.description_md:
        # local: memory imports the task modules
        from app.memory.sources import queue_extract

        await queue_extract(db, "task", task.id)
    task.updated_at = _now()
    return task


def deleted_with(task: Task):
    """Select of the ids delete_task removes: the task and, unless it is an epic (whose children are
    detached), the subtasks the parent_id cascade takes with it."""
    if task.type == TaskType.epic:
        return select(Task.id).where(Task.id == task.id)
    tree = select(Task.id).where(Task.id == task.id).cte("deleted_tree", recursive=True)
    tree = tree.union_all(select(Task.id).where(Task.parent_id == tree.c.id))
    return select(tree.c.id)


async def delete_task(db: AsyncSession, task: Task) -> None:
    if task.type == TaskType.epic:
        await db.execute(update(Task).where(Task.parent_id == task.id).values(parent_id=None))
    await db.delete(task)
    # local: memory imports the task modules
    from app.memory.sources import queue_forget

    await queue_forget(db)


async def list_tasks(
    db: AsyncSession,
    project: Project,
    *,
    type_: TaskType | None = None,
    assignee: str | None = None,
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
        is_agent = assignee.startswith("agent:")
        try:
            who = uuid.UUID(assignee.removeprefix("agent:"))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_assignee")
        stmt = stmt.where((Task.assignee_agent_id if is_agent else Task.assignee_user_id) == who)
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
    elif sprint == "active":
        from app.sprints.models import Sprint, SprintState

        stmt = stmt.where(
            Task.sprint_id.in_(
                select(Sprint.id).where(Sprint.project_id == project.id, Sprint.state == SprintState.active)
            )
        )
    elif sprint:
        try:
            stmt = stmt.where(Task.sprint_id == uuid.UUID(sprint))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_sprint")
    return list((await db.execute(stmt)).scalars())



async def _column_tasks(db: AsyncSession, column_id: uuid.UUID, exclude: uuid.UUID) -> list[Task]:
    rows = await db.execute(
        select(Task).where(Task.column_id == column_id, Task.id != exclude).order_by(Task.position, Task.number)
    )
    return list(rows.scalars())


async def move_task(db: AsyncSession, user: User, project: Project, task: Task, data: MoveIn) -> Task:
    """Drops the task into `column_id` below `before_key` and above `after_key`."""
    column = await get_column(db, project, data.column_id)
    siblings = await _column_tasks(db, column.id, exclude=task.id)
    by_key = {f"{project.key}-{t.number}": i for i, t in enumerate(siblings)}

    def index_of(key: str | None) -> int | None:
        if key is None:
            return None
        i = by_key.get(key.upper())
        if i is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_neighbor")
        return i

    bi, ai = index_of(data.before_key), index_of(data.after_key)
    # one neighbour is enough: the other is whatever card is adjacent to it
    if bi is not None and ai is None:
        ai = bi + 1 if bi + 1 < len(siblings) else None
    elif ai is not None and bi is None:
        bi = ai - 1 if ai > 0 else None
    elif bi is None and ai is None:
        bi = len(siblings) - 1 if siblings else None  # no neighbours given: append
    if bi is not None and ai is not None and ai != bi + 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_neighbor")

    def pos(i: int | None) -> float | None:
        return siblings[i].position if i is not None else None

    new_pos = ordering.position_between(pos(bi), pos(ai))
    if bi is not None and ai is not None and (
        ordering.needs_rebalance(pos(bi), new_pos) or ordering.needs_rebalance(new_pos, pos(ai))
    ):
        # gap exhausted: renumber the column, then split the fresh gap
        for n, t in enumerate(siblings, start=1):
            t.position = n * ordering.STEP
        await db.flush()
        new_pos = ordering.position_between(pos(bi), pos(ai))
    # imported here: the workflow engine imports this module
    from app.workflow import board

    await board.before_move(db, user, task, column)  # may refuse, or start, resume or pause the workflow
    task.position = new_pos
    if column.id != task.column_id:
        await record_event(db, task, user.id, "status_changed", {
            "from_column": str(task.column_id), "to_column": str(column.id), "to_category": str(column.category)})
    apply_column(task, column)
    task.updated_at = _now()
    return task


async def add_link(db: AsyncSession, user: User, project: Project, task: Task, target_key: str, kind: LinkKind) -> TaskLink:
    target, _ = await get_task_for(db, user, target_key)
    if target.id == task.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "cannot_link_to_self")
    if target.project_id != task.project_id:
        # cross-project links would show the other task's title to people without access to it
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "cross_project_link")
    exists = (
        await db.execute(
            select(TaskLink.id).where(
                TaskLink.kind == kind,
                ((TaskLink.source_id == task.id) & (TaskLink.target_id == target.id))
                | ((TaskLink.source_id == target.id) & (TaskLink.target_id == task.id) & (kind == LinkKind.relates)),
            )
        )
    ).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "link_exists")
    link = TaskLink(source_id=task.id, target_id=target.id, kind=kind)
    db.add(link)
    await db.flush()
    return link


async def remove_watcher(db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await db.execute(
        delete(task_watchers).where(task_watchers.c.task_id == task_id, task_watchers.c.user_id == user_id)
    )
