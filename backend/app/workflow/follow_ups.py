"""Follow-up tasks a design proposes for the later phases of a split task (MC-81): checked when the agent submits
the design and when a person approves it, and created on approval. Workflow runs never create tasks themselves."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select

from app.auth.models import User
from app.core.text import strip_nul
from app.projects.models import Project
from app.tasks.models import LinkKind, Task, TaskLink, TaskType
from app.tasks.schemas import TaskCreate, TaskUpdate
from app.tasks.service import create_task, record_event, task_changed, update_task
from app.workflow.models import DocKind, DocStatus, WorkflowDocument

MAX_FOLLOW_UPS = 10
MAX_TITLE = 500
MAX_DESCRIPTION = 4_000
TYPES = frozenset({TaskType.story.value, TaskType.task.value, TaskType.bug.value})


def _422(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


def _entry(item, *, reviewed: bool) -> dict:
    if not isinstance(item, dict):
        raise _422("invalid_follow_ups")
    title, kind, description = item.get("title", ""), item.get("type", "task"), item.get("description_md", "")
    if not all(isinstance(v, str) for v in (title, kind, description)) or kind not in TYPES:
        raise _422("invalid_follow_ups")
    title, description = strip_nul(title).strip(), strip_nul(description)
    entry = {"title": title, "type": kind, "description_md": description, "task_id": None}
    if reviewed:
        create = item.get("create")
        if not isinstance(create, bool):
            raise _422("invalid_follow_ups")
        entry["create"] = create
    if not title and (not reviewed or entry["create"]):
        raise _422("invalid_follow_ups")
    if len(title) > MAX_TITLE or len(description) > MAX_DESCRIPTION:
        raise _422("too_large")
    return entry


def _list(items) -> list:
    if not isinstance(items, list) or len(items) > MAX_FOLLOW_UPS:
        raise _422("invalid_follow_ups")
    return items


def clean_proposed(items) -> list[dict]:
    """What the agent passed to submit_design. None (left out) proposes none."""
    if items is None:
        return []
    return [_entry(i, reviewed=False) for i in _list(items)]


def clean_reviewed(items) -> list[dict]:
    """What the person sent with the approval: the whole list in order, each with `create`. An unticked row the
    person left without a title is dropped."""
    entries = [_entry(i, reviewed=True) for i in _list(items)]
    return [e for e in entries if e["title"]]


def task_path(project_key: str, number: int) -> str:
    return f"/projects/{project_key}/tasks/{number}"


def backlink(project_key: str, number: int, version: int) -> str:
    """The line that ends a created task's description: where it came from."""
    path = task_path(project_key, number)
    return (f"Follow-up of [{project_key}-{number}]({path}), from its "
            f"[approved design (v{version})]({path}#document-design-v{version}).")


async def _epic_id(db, task: Task) -> uuid.UUID | None:
    if task.parent_id is None:
        return None
    parent = await db.get(Task, task.parent_id)
    return parent.id if parent is not None and parent.type == TaskType.epic else None


async def create_on_approval(db, user: User, task: Task, doc: WorkflowDocument, reviewed: list[dict]) -> None:
    """Create the ticked entries of the approved design, in order: unassigned, in the first before-work column,
    in the task's epic, each linked to the task and recorded on it. The approved version keeps the reviewed list,
    with the created tasks' ids, and the task's description gets the scope note. Runs inside decide's transaction:
    a failure undoes the approval too."""
    project = await db.get(Project, task.project_id)
    epic_id = await _epic_id(db, task)
    tail = backlink(project.key, task.number, doc.version)
    entries, created = [], []
    for item in reviewed:
        entry = {"title": item["title"], "type": item["type"], "description_md": item["description_md"],
                 "task_id": None}
        if item["create"]:
            new = await create_task(db, user, project, TaskCreate(
                title=item["title"], type=TaskType(item["type"]),
                description_md=f"{item['description_md'].rstrip()}\n\n{tail}".lstrip(), parent_id=epic_id,
            ))
            await task_changed(db, new, "task.created")  # live boards show it
            db.add(TaskLink(source_id=task.id, target_id=new.id, kind=LinkKind.relates))
            await record_event(db, task, user.id, "follow_up_created", {
                "key": f"{project.key}-{new.number}", "title": new.title, "task_id": str(new.id),
                "type": str(new.type), "design_version": doc.version,
            })
            entry["task_id"] = str(new.id)
            created.append(new)
        entries.append(entry)
    doc.follow_ups = entries  # a new list: edits inside nested dicts are not tracked
    if created:
        await _write_scope_note(db, user, project, task, doc, created)


def scope_note(phases: list[tuple[str, str]], design_link: str) -> str:
    """`phases`: (key, path) of every follow-up task, in order. This task is phase 1."""
    total = len(phases) + 1
    links = ", ".join(f"[{key}]({path})" for key, path in phases)
    later = "Phase 2" if total == 2 else f"Phases 2–{total}"   # an en dash
    return f"Scope: phase 1 of {total} (per the [approved design]({design_link})). {later} → {links}."


def _other_approved(task: Task, doc: WorkflowDocument):
    return (WorkflowDocument.task_id == task.id, WorkflowDocument.kind == DocKind.design,
            WorkflowDocument.status == DocStatus.approved, WorkflowDocument.id != doc.id)


async def earlier(db, task: Task, doc: WorkflowDocument) -> list[Task]:
    """Follow-up tasks the task's other approved design versions created and that still exist, oldest first."""
    lists = (await db.execute(select(WorkflowDocument.follow_ups).where(*_other_approved(task, doc))
                              .order_by(WorkflowDocument.version))).scalars()
    ids = [uuid.UUID(e["task_id"]) for entries in lists for e in (entries or []) if e.get("task_id")]
    if not ids:
        return []
    found = {t.id: t for t in (await db.execute(select(Task).where(Task.id.in_(ids)))).scalars()}
    return [found[i] for i in ids if i in found]


async def _write_scope_note(db, user, project, task, doc, created: list[Task]) -> None:
    phases = [(f"{project.key}-{t.number}", task_path(project.key, t.number))
              for t in [*await earlier(db, task, doc), *created]]
    design_link = f"{task_path(project.key, task.number)}#document-design-v{doc.version}"
    note = scope_note(phases, design_link)
    previous = await db.scalar(
        select(WorkflowDocument.scope_note)
        .where(*_other_approved(task, doc), WorkflowDocument.scope_note.is_not(None))
        .order_by(WorkflowDocument.version.desc()).limit(1)
    )
    current = task.description_md or ""
    if previous and previous in current:  # the note the system wrote before, unedited: replace its last copy
        i = current.rindex(previous)
        text = current[:i] + note + current[i + len(previous):]
    else:
        text = f"{current.rstrip()}\n\n{note}" if current.strip() else note
    # a normal description change: field_changed is recorded and the memory update is queued
    await update_task(db, user, project, task, TaskUpdate(description_md=text))
    doc.scope_note = note
