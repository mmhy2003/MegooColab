"""The trigger events: for each, how a trigger's config is checked, matched, described and tried on the newest match.

A payload is a plain dict, ids as strings, written by the hook site (emit.py) or by `latest` for "Try it".
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC

from fastapi import HTTPException, status
from sqlalchemy import Select, String, and_, cast, exists, func, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.auth.models import User
from app.core.config import get_settings
from app.crons.models import Cron, CronRun, CronRunStatus
from app.projects.models import BoardColumn, ColumnCategory, Label, Project, ProjectRepository
from app.sprints.models import Sprint, SprintState
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


# ---- sprint, epic, cron and pull request events -------------------------------------------------------------


def _no_config(sprints: bool = False):
    async def validate(db: AsyncSession, project: Project, config: dict) -> dict:
        if sprints and not project.sprints_enabled:
            raise invalid("invalid_event")
        if not isinstance(config, dict) or config:
            raise invalid("invalid_config")
        return {}

    return validate


def _always(config: dict, payload: dict) -> bool:
    return True


async def _task_lines(db: AsyncSession, project: Project, *where) -> list[str]:
    """`- KEY [column] title` for each board task (no chat round) the conditions select, by number."""
    rows = (await db.execute(
        select(Task.number, BoardColumn.name, Task.title).join(BoardColumn, BoardColumn.id == Task.column_id)
        .where(Task.project_id == project.id, Task.in_chat.is_(False), *where).order_by(Task.number))).all()
    return [f"- {project.key}-{number} [{column}] {title}" for number, column, title in rows]


def _sprint_describer(event: TriggerEvent):
    async def describe(db: AsyncSession, payload: dict) -> Described:
        sprint = await db.get(Sprint, uuid.UUID(payload["sprint_id"]))
        project = await db.get(Project, sprint.project_id)
        link = f"/projects/{project.key}/backlog"
        note = "started" if event == TriggerEvent.sprint_started else "completed"
        lines = [f'Sprint "{sprint.name}" was {note}.',
                 f"Dates: {sprint.start_date.isoformat()} to {sprint.end_date.isoformat()}"]
        if sprint.goal:
            lines.append(f"Goal: {sprint.goal}")
        if event == TriggerEvent.sprint_completed:
            lines.append(f"Points: {sprint.completed_points or 0} of {sprint.committed_points or 0} "
                         "committed points completed")
        lines.append(f"Link: {_abs(link)}")
        tasks = await _task_lines(db, project, Task.sprint_id == sprint.id)
        return Described(
            subject={"kind": "sprint", "label": sprint.name, "title": sprint.goal or "", "link": link, "note": note},
            what=_cut("\n".join(lines) + "\n\nTasks:\n", "\n".join(tasks)),
        )

    return describe


async def _latest_sprint_completed(db: AsyncSession, trigger: Trigger) -> dict | None:
    sprint_id = await db.scalar(
        select(Sprint.id).where(Sprint.project_id == trigger.project_id, Sprint.state == SprintState.completed)
        .order_by(Sprint.completed_at.desc().nulls_last()).limit(1))
    return {"sprint_id": str(sprint_id)} if sprint_id else None


async def _latest_sprint_started(db: AsyncSession, trigger: Trigger) -> dict | None:
    active = await db.scalar(select(Sprint.id).where(
        Sprint.project_id == trigger.project_id, Sprint.state == SprintState.active).limit(1))
    return {"sprint_id": str(active)} if active else await _latest_sprint_completed(db, trigger)


async def _describe_epic(db: AsyncSession, payload: dict) -> Described:
    epic = await db.get(Task, uuid.UUID(payload["epic_id"]))
    last = await db.get(Task, uuid.UUID(payload["task_id"]))
    project = await db.get(Project, epic.project_id)
    key = f"{project.key}-{epic.number}"
    link = f"/projects/{project.key}/tasks/{epic.number}"
    lines = [f'Epic {key} "{epic.title}" was completed: every task of it is in a Done column.']
    if last is not None:
        lines.append(f'Event: {project.key}-{last.number} "{last.title}" was the last to finish')
    lines.append(f"Link: {_abs(link)}")
    tasks = await _task_lines(db, project, Task.parent_id == epic.id)
    body = (epic.description_md or "") + "\n\nTasks:\n" + "\n".join(tasks)
    return Described(
        subject={"kind": "epic", "label": key, "title": epic.title, "link": link, "note": "completed"},
        what=_cut("\n".join(lines) + "\n\nDescription:\n", body),
    )


async def _latest_epic(db: AsyncSession, trigger: Trigger) -> dict | None:
    """The epic whose last task finished most recently, among those with tasks, all of them in a Done column."""
    child = aliased(Task)
    children = and_(child.parent_id == Task.id, child.in_chat.is_(False))
    not_done = (select(child.id).join(BoardColumn, BoardColumn.id == child.column_id)
                .where(children, BoardColumn.category != ColumnCategory.done))
    finished = select(func.max(child.completed_at)).where(children).scalar_subquery()
    epic_id = await db.scalar(
        select(Task.id).where(Task.project_id == trigger.project_id, Task.type == "epic",
                              exists(select(child.id).where(children)), ~exists(not_done))
        .order_by(finished.desc().nulls_last(), Task.created_at.desc()).limit(1))
    if epic_id is None:
        return None
    last = await db.scalar(select(Task.id).where(Task.parent_id == epic_id, Task.in_chat.is_(False))
                           .order_by(Task.completed_at.desc().nulls_last(), Task.number.desc()).limit(1))
    return {"epic_id": str(epic_id), "task_id": str(last)}


async def _validate_cron(db: AsyncSession, project: Project, config: dict) -> dict:
    if not isinstance(config, dict) or set(config) - {"cron_id"}:
        raise invalid("invalid_config")
    value = config.get("cron_id")
    if value is None:
        return {}
    if not isinstance(value, str):
        raise invalid("invalid_config")
    cron_id = _uuid(value)
    found = cron_id and await db.scalar(select(Cron.id).where(Cron.id == cron_id, Cron.project_id == project.id))
    if not found:
        raise invalid("invalid_cron")
    return {"cron_id": str(cron_id)}


def _cron_matches(config: dict, payload: dict) -> bool:
    return config.get("cron_id") in (None, payload["cron_id"])


def _findings(n: int) -> str:
    return f"{n} finding" if n == 1 else f"{n} findings"


async def _describe_cron(db: AsyncSession, payload: dict) -> Described:
    from app.crons.turns import cron_link  # local: the cron turns emit cron_found when a run ends

    cron = await db.get(Cron, uuid.UUID(payload["cron_id"]))
    run = await db.get(CronRun, uuid.UUID(payload["cron_run_id"]))
    project = await db.get(Project, cron.project_id)
    report = run.report or {}
    summary = report.get("summary") or ""
    findings = report.get("findings") or []
    link = cron_link(project.key, cron.id, run.id)
    at = (run.finished_at or run.scheduled_at).astimezone(UTC).strftime("%Y-%m-%d %H:%M")
    head = (f'Cron "{cron.name}" finished a run on {at} UTC with {_findings(len(findings))}.\n'
            f"Link: {_abs(link)}\n\nSummary:\n")
    entries = []
    for f in findings:
        entry = f"- {f.get('title', '')}: {f.get('detail', '')}"
        if f.get("task_key"):
            entry += f" (task {f['task_key']})"
        entries.append(entry)
    return Described(
        subject={"kind": "cron_run", "label": cron.name, "title": summary[:200], "link": link,
                 "note": _findings(len(findings))},
        what=_cut(head, summary + "\n\nFindings:\n" + "\n".join(entries)),
    )


async def _latest_cron(db: AsyncSession, trigger: Trigger) -> dict | None:
    config = trigger.config or {}
    findings = CronRun.report["findings"]
    stmt = (select(CronRun.cron_id, CronRun.id).join(Cron, Cron.id == CronRun.cron_id)
            .where(Cron.project_id == trigger.project_id, CronRun.status == CronRunStatus.done,
                   func.jsonb_typeof(findings) == "array", cast(findings, String) != "[]")
            .order_by(CronRun.finished_at.desc().nulls_last(), CronRun.scheduled_at.desc()).limit(1))
    if config.get("cron_id") is not None:
        stmt = stmt.where(Cron.id == _uuid(config["cron_id"]))
    row = (await db.execute(stmt)).first()
    return {"cron_id": str(row[0]), "cron_run_id": str(row[1])} if row is not None else None


async def _describe_pr(db: AsyncSession, payload: dict) -> Described:
    repo = await db.get(ProjectRepository, uuid.UUID(payload["repo_id"]))
    n, title, base = payload["number"], payload["title"], payload["base"]
    lines = [f'Pull request #{n} "{title}" was merged into {base} of repository {repo.name} by {payload["actor"]}.',
             f"Branch: {payload['branch']}", f"URL: {payload['url']}"]
    return Described(
        subject={"kind": "pr", "label": f"#{n}", "title": title, "link": payload["url"],
                 "note": f"merged into {base}"},
        what=_cut("\n".join(lines), ""),
    )


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
        EventSpec(TriggerEvent.sprint_started, _no_config(sprints=True), _always,
                  _sprint_describer(TriggerEvent.sprint_started), _latest_sprint_started, sprints_only=True),
        EventSpec(TriggerEvent.sprint_completed, _no_config(sprints=True), _always,
                  _sprint_describer(TriggerEvent.sprint_completed), _latest_sprint_completed, sprints_only=True),
        EventSpec(TriggerEvent.epic_completed, _no_config(), _always, _describe_epic, _latest_epic),
        EventSpec(TriggerEvent.cron_found, _validate_cron, _cron_matches, _describe_cron, _latest_cron),
        EventSpec(TriggerEvent.pr_merged, _no_config(), _always, _describe_pr, None),
    )
}
