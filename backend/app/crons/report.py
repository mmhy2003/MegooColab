"""A cron run's report, and what MegooColab does with it per the cron's mode: keep it, open tasks for real problems
(at most MAX_TASKS, labelled "from cron"), or rewrite the cron's one Knowledge Base document."""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.auth.models import User
from app.core.text import strip_nul
from app.crons.models import Cron, CronMode, CronRun
from app.crons.turns import cron_link
from app.kb import access as kb_access
from app.kb import service as kb
from app.kb.models import KbDocument
from app.projects.models import Label, Project
from app.tasks.models import Task
from app.tasks.schemas import TaskCreate

MAX_TASKS = 5
MAX_FINDINGS = 50
LABEL = "from cron"
LABEL_COLOR = "#c084fc"
SUMMARY_MAX, TITLE_MAX, DETAIL_MAX, CHECKED_MAX = 2000, 200, 5000, 5000


def _refuse(code: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, code)


def _text(value: Any, limit: int) -> str:
    return strip_nul(str(value or "")).strip()[:limit]


async def _label(db: AsyncSession, project: Project) -> Label:
    label = await db.scalar(select(Label).where(Label.project_id == project.id, Label.name == LABEL))
    if label is None:
        label = Label(project_id=project.id, name=LABEL, color=LABEL_COLOR)
        db.add(label)
        await db.flush()
    return label


async def _project_task(db: AsyncSession, project: Project, key: str) -> Task | None:
    prefix, _, number = key.strip().upper().rpartition("-")
    if prefix != project.key.upper() or not number.isdigit():
        return None
    return await db.scalar(select(Task).where(Task.project_id == project.id, Task.number == int(number)))


async def _open_tasks(db, owner: User, project: Project, cron: Cron, cron_run: CronRun, findings: list[dict],
                      notes: list[str]) -> int:
    from app.tasks.activity import create_comment  # local: the tasks package imports the agent runs
    from app.tasks.service import create_task

    link = cron_link(project.key, cron.id, cron_run.id)
    created, left = 0, 0
    for f in findings:
        key = f.get("existing_task_key")
        if key:
            task = await _project_task(db, project, str(key))
            if task is None:
                notes.append(f"{key} isn't a task of {project.key}: no comment was added.")
                continue
            await create_comment(db, owner, f"{project.key}-{task.number}",
                                 f"Cron **{cron.name}** found this again: {f['title']}\n\n{f['detail']}\n\n[The run]({link})")
            f["task_key"] = f"{project.key}-{task.number}"
        elif f.get("new_task"):
            if created >= MAX_TASKS:
                left += 1
                continue
            label = await _label(db, project)
            task = await create_task(db, owner, project, TaskCreate(
                title=f["title"], description_md=f"{f['detail']}\n\nFrom cron {cron.name}: {link}", label_ids=[label.id]))
            f["task_key"], f["created"] = f"{project.key}-{task.number}", True
            created += 1
    if left:
        notes.append(f"{left} more tasks not created: the limit is {MAX_TASKS} per run.")
    return created


async def _write_document(db, owner: User, run: AgentRun, project: Project, cron: Cron, body: str) -> None:
    summary = f"Cron: {cron.name}"
    doc = await db.get(KbDocument, cron.kb_document_id) if cron.kb_document_id else None
    if doc is None:  # the first run, or the document was deleted: (re)created at the top of the project's space
        space = await kb_access.space_for_project(db, project.id)
        title = await kb.free_title(db, space.id, None, cron.kb_title or cron.name)
        doc = await kb.create_document(db, owner, space, None, title, body, agent_id=run.agent_id, summary=summary)
        cron.kb_document_id = doc.id
    else:
        await kb.update_document(db, owner, doc, base_revision=doc.latest_revision, body=body, summary=summary,
                                 agent_id=run.agent_id)


async def apply_report(db: AsyncSession, run: AgentRun, *, summary: str, findings: list[dict[str, Any]],
                       checked: str, nothing_new: bool, document_md: str | None) -> dict[str, Any]:
    cron_run = (
        await db.execute(
            select(CronRun).where(CronRun.id == run.cron_run_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if cron_run is None:
        raise _refuse("cron_gone")
    run = (
        await db.execute(
            select(AgentRun).where(AgentRun.id == run.id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one()
    if run.status != RunStatus.running or run.cancelled_by is not None:
        raise _refuse("run_not_running")
    if (cron_run.report or {}).get("submitted"):
        raise _refuse("already_submitted")
    cron = await db.get(Cron, cron_run.cron_id)
    project = await db.get(Project, cron.project_id)
    owner = await db.get(User, await db.scalar(select(Agent.owner_id).where(Agent.id == run.agent_id)))
    clean = [
        {"title": _text(f.get("title"), TITLE_MAX) or "Finding", "detail": _text(f.get("detail"), DETAIL_MAX),
         "new_task": bool(f.get("new_task")), "existing_task_key": _text(f.get("existing_task_key"), 50) or None}
        for f in (findings or [])[:MAX_FINDINGS] if isinstance(f, dict)
    ]
    notes: list[str] = []
    created = 0
    if cron.mode == CronMode.tasks:
        created = await _open_tasks(db, owner, project, cron, cron_run, clean, notes)
    elif cron.mode == CronMode.kb and document_md is not None:
        kb.check_body(document_md)
        await _write_document(db, owner, run, project, cron, strip_nul(document_md))
    for f in clean:
        f.pop("new_task", None)
        f.pop("existing_task_key", None)
    cron_run.report = {"summary": _text(summary, SUMMARY_MAX), "findings": clean, "checked": _text(checked, CHECKED_MAX),
                       "nothing_new": bool(nothing_new), "notes": notes, "submitted": True}
    cron_run.tasks_created = created
    await db.flush()
    return {"ok": True, "tasks_created": created, "notes": notes}
