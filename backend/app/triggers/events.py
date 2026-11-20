"""The trigger events: for each, how a trigger's config is checked, matched, described and tried on the newest match.

A payload is a plain dict, ids as strings, written by the hook site (emit.py) or by `latest` for "Try it".
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.auth.models import User
from app.core.config import get_settings
from app.projects.models import BoardColumn, ColumnCategory, Label, Project
from app.tasks.models import Task, task_labels
from app.triggers.models import WHAT_CHARS, Trigger, TriggerEvent
from app.workflow.models import Needs, TaskWorkflow

TASK_TYPES = ("story", "task", "bug")
CUT_NOTE = "\n(cut to fit)"


@dataclass(frozen=True)
class Described:
    subject: dict  # {"kind", "label", "title", "link", "note"}
    what: str  # cut to WHAT_CHARS


@dataclass(frozen=True)
class EventSpec:
    id: TriggerEvent
    validate: Callable[[AsyncSession, Project, dict], Awaitable[dict]]  # cleaned config, or raises invalid(code)
    matches: Callable[[dict, dict], bool]  # (config, payload), pure
    describe: Callable[[AsyncSession, dict], Awaitable[Described]]  # payload -> history row + What happened
    latest: Callable[[AsyncSession, Trigger], Awaitable[dict | None]] | None  # newest match, for Try it
    sprints_only: bool = False


def invalid(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


def spec(event: str) -> EventSpec:
    found = REGISTRY.get(event)
    if found is None:
        raise invalid("invalid_event")
    return found


def _abs(link: str) -> str:
    return get_settings().public_url.rstrip("/") + link


def _cut(head: str, body: str) -> str:
    """`head` and then `body`, within WHAT_CHARS: the body is cut first."""
    text = head + body
    if len(text) <= WHAT_CHARS:
        return text
    room = WHAT_CHARS - len(head) - len(CUT_NOTE)
    if room < 0:
        return head[: WHAT_CHARS - len(CUT_NOTE)] + CUT_NOTE
    return head + body[:room] + CUT_NOTE


async def _actor_name(db: AsyncSession, actor: User | None) -> str:
    from app.mcp_server.auth import current_run  # local: the MCP tools import the task service, which emits

    run = current_run.get()
    if run is not None and run.agent_id is not None:
        name = await db.scalar(select(Agent.name).where(Agent.id == run.agent_id))
        if name:
            return name
    return actor.name if actor is not None else "the workflow"


# ---- task events ---------------------------------------------------------------------------------------------


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _task_validator(with_column: bool):
    keys = {"task_types", "label_id"} | ({"column_id"} if with_column else set())

    async def validate(db: AsyncSession, project: Project, config: dict) -> dict:
        if not isinstance(config, dict) or set(config) - keys:
            raise invalid("invalid_config")
        types = config.get("task_types")
        if types is not None and not isinstance(types, list):
            raise invalid("invalid_config")
        if not types:
            raise invalid("no_task_types")
        if any(t not in TASK_TYPES for t in types):
            raise invalid("invalid_config")
        cleaned: dict = {"task_types": [t for t in TASK_TYPES if t in types]}
        label = config.get("label_id")
        if label is not None:
            if not isinstance(label, str):
                raise invalid("invalid_config")
            label_id = _uuid(label)
            found = label_id and await db.scalar(
                select(Label.id).where(Label.id == label_id, Label.project_id == project.id))
            if not found:
                raise invalid("invalid_label")
            cleaned["label_id"] = str(label_id)
        if with_column:
            column_id = _uuid(config.get("column_id"))
            found = column_id and await db.scalar(
                select(BoardColumn.id).where(BoardColumn.id == column_id, BoardColumn.project_id == project.id))
            if not found:
                raise invalid("invalid_column")
            cleaned["column_id"] = str(column_id)
        return cleaned

    return validate


def _task_matches(config: dict, payload: dict) -> bool:
    label = config.get("label_id")
    return payload["type"] in config.get("task_types", ()) and (label is None or label in payload["label_ids"])


def _moved_matches(config: dict, payload: dict) -> bool:
    return _task_matches(config, payload) and payload["column_id"] == config.get("column_id")


async def task_payload(db: AsyncSession, task: Task, *, from_column_id: uuid.UUID | None = None,
                       actor: User | None = None, reason: str | None = None) -> dict:
    label_ids = (await db.execute(
        select(task_labels.c.label_id).where(task_labels.c.task_id == task.id))).scalars().all()
    payload = {
        "task_id": str(task.id),
        "type": str(task.type),
        "label_ids": sorted(str(i) for i in label_ids),
        "column_id": str(task.column_id),
        "from_column_id": str(from_column_id) if from_column_id else None,
        "actor": await _actor_name(db, actor),
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


async def _column_name(db: AsyncSession, column_id: str | None) -> str | None:
    column_id = _uuid(column_id)
    return column_id and await db.scalar(select(BoardColumn.name).where(BoardColumn.id == column_id))


def _task_describer(event: TriggerEvent):
    async def describe(db: AsyncSession, payload: dict) -> Described:
        task = await db.get(Task, uuid.UUID(payload["task_id"]))
        project = await db.get(Project, task.project_id)
        key = f"{project.key}-{task.number}"
        link = f"/projects/{project.key}/tasks/{task.number}"
        labels = (await db.execute(
            select(Label.name).join(task_labels, task_labels.c.label_id == Label.id)
            .where(task_labels.c.task_id == task.id).order_by(Label.name))).scalars().all()
        reason = (payload.get("reason") or "").replace("_", " ")
        if event == TriggerEvent.task_moved:
            to = await _column_name(db, payload["column_id"]) or "a column"
            source = await _column_name(db, payload.get("from_column_id"))
            note = f"moved to {to}"
            happened = f"moved from {source} to {to}" if source else note
        elif event == TriggerEvent.task_needs_person:
            note, happened = f"needs a person: {reason}", f"escalated: {reason}"
        else:
            note = happened = "finished" if event == TriggerEvent.task_finished else "created"

        kind = f"{task.type}; labels: {', '.join(labels)}" if labels else str(task.type)
        lines = [f'Task {key} "{task.title}" ({kind})', f"Event: {happened} by {payload['actor']}",
                 f"Link: {_abs(link)}"]
        epic = await db.get(Task, task.parent_id) if task.parent_id else None
        if epic is not None and epic.type == "epic":
            lines.append(f'Epic: {project.key}-{epic.number} "{epic.title}"')
        head = "\n".join(lines) + "\n\nDescription:\n"
        return Described(
            subject={"kind": "task", "label": key, "title": task.title, "link": link, "note": note},
            what=_cut(head, task.description_md or ""),
        )

    return describe


def _board_tasks(trigger: Trigger) -> Select:
    """The project's board tasks (no chat rounds, no epics or subtasks) the trigger's types and label allow."""
    config = trigger.config or {}
    stmt = select(Task).where(
        Task.project_id == trigger.project_id, Task.in_chat.is_(False),
        Task.type.in_([t for t in config.get("task_types", ()) if t in TASK_TYPES]))
    label = _uuid(config.get("label_id"))
    if config.get("label_id") is not None:
        stmt = stmt.where(Task.id.in_(select(task_labels.c.task_id).where(task_labels.c.label_id == label)))
    return stmt


async def _payload_of(db: AsyncSession, stmt: Select, **kw) -> dict | None:
    task = (await db.execute(stmt.limit(1))).scalars().first()
    return await task_payload(db, task, **kw) if task is not None else None


async def _latest_finished(db: AsyncSession, trigger: Trigger) -> dict | None:
    stmt = (_board_tasks(trigger).join(BoardColumn, BoardColumn.id == Task.column_id)
            .where(BoardColumn.category == ColumnCategory.done).order_by(Task.completed_at.desc().nulls_last()))
    return await _payload_of(db, stmt)


async def _latest_created(db: AsyncSession, trigger: Trigger) -> dict | None:
    return await _payload_of(db, _board_tasks(trigger).order_by(Task.created_at.desc()))


async def _latest_moved(db: AsyncSession, trigger: Trigger) -> dict | None:
    column = _uuid((trigger.config or {}).get("column_id"))
    if column is None:
        return None
    stmt = _board_tasks(trigger).where(Task.column_id == column).order_by(Task.updated_at.desc())
    return await _payload_of(db, stmt)


async def _latest_needs_person(db: AsyncSession, trigger: Trigger) -> dict | None:
    stmt = (_board_tasks(trigger).add_columns(TaskWorkflow.escalation_reason)
            .join(TaskWorkflow, TaskWorkflow.task_id == Task.id)
            .where(TaskWorkflow.needs == Needs.escalation).order_by(Task.updated_at.desc()).limit(1))
    row = (await db.execute(stmt)).first()
    return await task_payload(db, row[0], reason=row[1] or "") if row is not None else None


REGISTRY: dict[str, EventSpec] = {
    s.id: s
    for s in (
        EventSpec(TriggerEvent.task_finished, _task_validator(False), _task_matches,
                  _task_describer(TriggerEvent.task_finished), _latest_finished),
        EventSpec(TriggerEvent.task_created, _task_validator(False), _task_matches,
                  _task_describer(TriggerEvent.task_created), _latest_created),
        EventSpec(TriggerEvent.task_moved, _task_validator(True), _moved_matches,
                  _task_describer(TriggerEvent.task_moved), _latest_moved),
        EventSpec(TriggerEvent.task_needs_person, _task_validator(False), _task_matches,
                  _task_describer(TriggerEvent.task_needs_person), _latest_needs_person),
    )
}
