"""Bug tasks for the known failing tests a finish reported (MC-100): a person asks for one per test from the
workflow panel, and a test that already has an open bug in the project links to it instead. One bug per test,
matched on `tasks.failing_test`. Workflow runs never create them (as follow_ups)."""

import re
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select

from app.auth.models import User
from app.kb.filing import _code_span
from app.projects.models import BoardColumn, ColumnCategory, Project
from app.tasks.models import LinkKind, Task, TaskLink, TaskType
from app.tasks.schemas import TaskCreate
from app.tasks.service import create_task, task_changed
from app.tasks.visibility import on_board
from app.workflow import engine
from app.workflow.follow_ups import _chat, task_path
from app.workflow.models import Stage, TaskWorkflow, WorkflowTestRun

OFFERED = ("base", "flaky")

# ":42" or ":42:5" right after a file extension: Playwright's position, which moves when the file is edited above it
_POSITION = re.compile(r"(\.[A-Za-z0-9]{1,10}):\d+(?::\d+)?(?!\w)")


def test_key(name: str) -> str:
    """The match key of a reported test name: whitespace collapsed, a position after a file name removed."""
    return _POSITION.sub(r"\1", " ".join(name.split()))


async def open_bugs(db, project_id: uuid.UUID, keys) -> dict[str, Task]:
    """The open bug of each key: on the board, not in a Done column. Of several, the lowest number."""
    keys = set(keys)
    if not keys:
        return {}
    rows = await db.execute(
        select(Task).join(BoardColumn, BoardColumn.id == Task.column_id)
        .where(Task.project_id == project_id, Task.failing_test.in_(keys), on_board(),
               BoardColumn.category != ColumnCategory.done)
        .order_by(Task.number)
    )
    found: dict[str, Task] = {}
    for t in rows.scalars():
        found.setdefault(t.failing_test, t)
    return found


def _409(code: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, code)


def title(name: str, kind: str) -> str:
    return f"{'Flaky' if kind == 'flaky' else 'Failing'} test: {' '.join(name.split())}"


def description(*, name: str, kind: str, source: str, start_branch: str | None, seen_on: str,
                command: str | None) -> str:
    """`source`: Markdown naming where it was seen (a task link, or the chat). Agent-written text is in code spans."""
    branch = _code_span(start_branch) if start_branch else "the start branch"
    if kind == "base":
        lead = f"This test already failed on the commit that {source} started from, on {branch}."
        kind_text = f"also fails on {branch}"
    else:
        lead = f"This test failed and then passed when it was run again at the finish of {source}."
        kind_text = "flaky"
    lines = [lead, "", f"- Test: {_code_span(name)}", f"- Kind: {kind_text}", f"- Seen at: {source}, {seen_on}"]
    if command:
        lines.append(f"- Command: {_code_span(command)}")
    return "\n".join(lines)


async def _command(db, task_id: uuid.UUID, name: str) -> str | None:
    """The command of the newest test run the task recorded at finish (not on the start commit) that failed the test."""
    rows = await db.execute(
        select(WorkflowTestRun)
        .where(WorkflowTestRun.task_id == task_id, WorkflowTestRun.stage == Stage.done,
               WorkflowTestRun.on_base.is_(False))
        .order_by(WorkflowTestRun.created_at.desc(), WorkflowTestRun.id.desc())
    )
    return next((r.command for r in rows.scalars() if name in (r.failing or [])), None)


async def create(db, user: User, project: Project, task: Task, name: str) -> None:
    """The bug for a known failing test the task's finish listed, unless the project has an open one already:
    unassigned, in the first before-work column, no epic, linked to the task and recorded on it. A chat round's
    bug gets no link and points back at the chat."""
    wf = await db.get(TaskWorkflow, task.id)
    failures = ((wf.finish_tests if wf is not None else None) or {}).get("failures") or []
    failure = next((f for f in failures if f.get("name") == name and f.get("kind") in OFFERED), None)
    if failure is None:
        raise _409("failure_not_listed")
    key = test_key(name)
    # one open bug per test in the project: a concurrent click, on this task or another, waits here and then sees it
    await db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    if await open_bugs(db, project.id, [key]):
        return
    chat = await _chat(db, task)
    source = (f"a round of the chat [{chat.title}](/chats/{chat.id})" if chat is not None
              else f"[{project.key}-{task.number}]({task_path(project.key, task.number)})")
    bug = await create_task(db, user, project, TaskCreate(
        title=title(name, failure["kind"]), type=TaskType.bug,
        description_md=description(name=name, kind=failure["kind"], source=source, start_branch=task.start_branch,
                                   seen_on=datetime.now(UTC).date().isoformat(),
                                   command=await _command(db, task.id, name)),
    ))
    bug.failing_test = key
    await task_changed(db, bug, "task.created")  # live boards show it
    if chat is None:
        db.add(TaskLink(source_id=task.id, target_id=bug.id, kind=LinkKind.relates))
    await engine.record_workflow_event(db, task, user.id, "finish.bug_created", {
        "key": f"{project.key}-{bug.number}", "title": bug.title, "task_id": str(bug.id),
        "name": name, "kind": failure["kind"],
    })
