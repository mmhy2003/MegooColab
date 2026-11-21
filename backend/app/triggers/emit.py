"""The hook sites' entry points: each writes a `pending` firing for every unpaused trigger its event matches.

Nothing is started here (the trigger loop does that), and nothing here may fail the action that emitted: the
firings are written in a savepoint, and an error is logged and dropped. What a triggered chat does never fires.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.crons.models import Cron, CronRun
from app.projects.models import BoardColumn, ColumnCategory, Project, ProjectStatus
from app.sprints.models import Sprint
from app.tasks.models import Task
from app.triggers import events as events_mod
from app.triggers.events import TASK_TYPES
from app.triggers.models import Trigger, TriggerEvent, TriggerFiring
from app.workflow.models import RunRole

log = logging.getLogger(__name__)


async def from_triggered_chat(db: AsyncSession) -> bool:
    """The loop guard: whether the change comes from a chat a trigger started."""
    from app.mcp_server.auth import current_run  # local: the MCP tools import the task service, which emits
    from app.tasks.service import event_origin  # local: the task service emits

    chat_id = None
    origin = event_origin.get()
    if origin is not None:
        chat_id = uuid.UUID(origin["id"])
    else:
        run = current_run.get()
        if run is not None and run.workflow_role == RunRole.freestyle and run.task_id is not None:
            chat_id = await db.scalar(select(Task.chat_id).where(Task.id == run.task_id))
    if chat_id is None:
        return False
    return bool(await db.scalar(select(exists().where(TriggerFiring.chat_id == chat_id))))


async def _emit(db: AsyncSession, project_id: uuid.UUID,
                events: list[tuple[str, Callable[[], Awaitable[dict | None]]]]) -> None:
    """`events`: each event with the builder of its payload, called only when a trigger listens; a builder
    returns None when, on a closer look, the event did not happen."""
    try:
        async with db.begin_nested():
            project = await db.get(Project, project_id)
            if project is None or project.status != ProjectStatus.active or await from_triggered_chat(db):
                return
            for event, build in events:
                triggers = (await db.execute(select(Trigger).where(
                    Trigger.project_id == project_id, Trigger.event == event, Trigger.paused.is_(False)
                ))).scalars().all()
                if not triggers:
                    continue
                payload = await build()
                if payload is None:
                    continue
                spec = events_mod.spec(event)
                hits = [t for t in triggers if spec.matches(t.config or {}, payload)]
                if hits:
                    d = await spec.describe(db, payload)
                    for t in hits:
                        db.add(TriggerFiring(trigger_id=t.id, event=event, subject=d.subject, what=d.what))
            await db.flush()
    except Exception:
        log.exception("triggers: emit failed")


def _board_task(task: Task) -> bool:
    return not task.in_chat and task.type in TASK_TYPES


async def task_created(db: AsyncSession, task: Task, actor: User | None) -> None:
    if not _board_task(task):
        return

    async def build() -> dict:
        return await events_mod.task_payload(db, task, actor=actor)

    await _emit(db, task.project_id, [(TriggerEvent.task_created, build)])


async def _completes_epic(db: AsyncSession, task: Task) -> bool:
    """Whether the task's parent is an epic none of whose tasks is still outside a Done column."""
    if task.parent_id is None:
        return False
    epic_type = await db.scalar(select(Task.type).where(Task.id == task.parent_id))
    if epic_type != "epic":
        return False
    open_child = (select(Task.id).join(BoardColumn, BoardColumn.id == Task.column_id)
                  .where(Task.parent_id == task.parent_id, Task.in_chat.is_(False),
                         BoardColumn.category != ColumnCategory.done))
    return not await db.scalar(select(exists(open_child)))


async def task_moved(db: AsyncSession, task: Task, from_column_id: uuid.UUID | None, to_column: BoardColumn,
                     actor: User | None) -> None:
    """`task_moved`; and, when it enters a Done column from one that is not, `task_finished` and perhaps
    `epic_completed`."""
    if not _board_task(task):
        return

    async def moved() -> dict:
        return await events_mod.task_payload(db, task, from_column_id=from_column_id, actor=actor)

    async def finishes() -> bool:
        if to_column.category != ColumnCategory.done:
            return False
        frm = from_column_id and await db.scalar(select(BoardColumn.category).where(BoardColumn.id == from_column_id))
        return frm != ColumnCategory.done  # no from-column counts as not done

    async def finished() -> dict | None:
        return await moved() if await finishes() else None

    async def epic() -> dict | None:
        if not (await finishes() and await _completes_epic(db, task)):
            return None
        return {"epic_id": str(task.parent_id), "task_id": str(task.id)}

    await _emit(db, task.project_id, [
        (TriggerEvent.task_moved, moved), (TriggerEvent.task_finished, finished), (TriggerEvent.epic_completed, epic),
    ])


async def task_needs_person(db: AsyncSession, task: Task, reason: str) -> None:
    """The task's workflow escalated: a person must decide."""
    if not _board_task(task):
        return

    async def build() -> dict:
        return await events_mod.task_payload(db, task, reason=reason)

    await _emit(db, task.project_id, [(TriggerEvent.task_needs_person, build)])


async def _sprint(db: AsyncSession, sprint: Sprint, event: TriggerEvent) -> None:
    async def build() -> dict:
        return {"sprint_id": str(sprint.id)}

    await _emit(db, sprint.project_id, [(event, build)])


async def sprint_started(db: AsyncSession, sprint: Sprint) -> None:
    await _sprint(db, sprint, TriggerEvent.sprint_started)


async def sprint_completed(db: AsyncSession, sprint: Sprint) -> None:
    await _sprint(db, sprint, TriggerEvent.sprint_completed)


async def cron_found(db: AsyncSession, cron: Cron, cron_run: CronRun) -> None:
    """A cron run ended `done` with findings (the hook site checks that)."""
    async def build() -> dict:
        return {"cron_id": str(cron.id), "cron_run_id": str(cron_run.id)}

    await _emit(db, cron.project_id, [(TriggerEvent.cron_found, build)])
