"""Bug tasks for the known failing tests a finish reported (MC-100)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.auth.models import Role
from app.core.db import SessionLocal
from app.projects.models import BoardColumn, ColumnCategory
from app.tasks.models import Task, TaskLink
from app.tasks.schemas import TaskCreate, TaskOut, TaskUpdate
from app.workflow import known_bugs
from app.workflow.models import Stage, TaskWorkflow, WorkflowStatus, WorkflowTestRun
from tests.factories import login, make_project, make_user
from tests.workflow.test_engine import _events

BASE = {"name": "e2e/a.spec.ts:42:5 › finishes a task", "kind": "base"}
FLAKY = {"name": "tests/x.py::test_y", "kind": "flaky"}
NEW = {"name": "e2e/b.spec.ts:3", "kind": "new"}


async def _task(client, title="Pay out", project="PAY") -> dict:
    r = await client.post(f"/api/projects/{project}/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


async def _finished(task: dict, failures, *, start_branch="develop") -> None:
    """The task's finish settled with these failures (as finish._settle_delivered leaves it)."""
    tid = uuid.UUID(task["id"])
    async with SessionLocal() as s:
        wf = await s.get(TaskWorkflow, tid) or TaskWorkflow(task_id=tid)
        wf.stage, wf.status = Stage.done, WorkflowStatus.finished
        wf.finish_tests = {"failures": failures, "failing_total": None, "diagnosis": None, "delivered": True,
                           "settled": "known"}
        s.add(wf)
        await s.execute(update(Task).where(Task.id == tid).values(start_branch=start_branch))
        await s.commit()


async def _bugs() -> list[Task]:
    async with SessionLocal() as s:
        rows = await s.execute(select(Task).where(Task.failing_test.is_not(None)).order_by(Task.number))
        return list(rows.scalars())


async def _to_done(task_id) -> None:
    async with SessionLocal() as s:
        t = await s.get(Task, task_id)
        t.column_id = await s.scalar(select(BoardColumn.id).where(
            BoardColumn.project_id == t.project_id, BoardColumn.category == ColumnCategory.done))
        await s.commit()


def _create(client, key, name):
    return client.post(f"/api/tasks/{key}/workflow/known-failures/bug", json={"name": name})


def test_failing_test_is_a_column_no_api_field():
    col = Task.__table__.c.failing_test
    assert col.nullable and col.type.length == 300
    for schema in (TaskCreate, TaskUpdate, TaskOut):
        assert "failing_test" not in schema.model_fields
    [ix] = [i for i in Task.__table__.indexes if i.name == "ix_tasks_project_failing_test"]
    assert [c.name for c in ix.columns] == ["project_id", "failing_test"]


def test_key_normalises():
    key = known_bugs.test_key
    assert key("e2e/a.spec.ts:42:5 › finishes") == "e2e/a.spec.ts › finishes"
    assert key("e2e/a.spec.ts:57:5 › finishes") == "e2e/a.spec.ts › finishes"
    assert key("legacy.test:1") == "legacy.test"
    assert key("  e2e/a.spec.ts:42 ›\n  title ") == "e2e/a.spec.ts › title"
    for name in ("tests/x.py::test_y", "x.test.ts > suite > title", "npx tsc --noEmit"):
        assert key(name) == name


async def test_open_bugs(client, db):
    pay, _, _ = await make_project(client, db, "PAY")
    pay_id = uuid.UUID(pay["id"])
    tasks = [await _task(client, f"Task {i}") for i in range(1, 5)]
    ids = [uuid.UUID(t["id"]) for t in tasks]
    async with SessionLocal() as s:
        await s.execute(update(Task).where(Task.id.in_(ids[:2])).values(failing_test="k1"))
        await s.execute(update(Task).where(Task.id == ids[2]).values(failing_test="k2"))
        await s.execute(update(Task).where(Task.id == ids[3]).values(failing_test="k3", in_chat=True))
        await s.commit()
    await _to_done(ids[2])
    await make_project(client, db, "SHOP")
    shop = await _task(client, "Shop task", project="SHOP")
    async with SessionLocal() as s:
        await s.execute(update(Task).where(Task.id == uuid.UUID(shop["id"])).values(failing_test="k4"))
        await s.commit()

    async def found() -> dict[str, str]:
        async with SessionLocal() as s:
            bugs = await known_bugs.open_bugs(s, pay_id, ["k1", "k2", "k3", "k4", "none"])
            return {k: f"PAY-{t.number}" for k, t in bugs.items()}

    assert [t["key"] for t in tasks] == ["PAY-1", "PAY-2", "PAY-3", "PAY-4"]
    assert await found() == {"k1": "PAY-1"}
    async with SessionLocal() as s:
        assert await known_bugs.open_bugs(s, pay_id, []) == {}

    await _to_done(ids[0])
    assert await found() == {"k1": "PAY-2"}
    async with SessionLocal() as s:
        first = await s.scalar(select(BoardColumn.id).where(
            BoardColumn.project_id == pay_id, BoardColumn.category == ColumnCategory.before,
        ).order_by(BoardColumn.position).limit(1))
        await s.execute(update(Task).where(Task.id == ids[0]).values(column_id=first))
        await s.commit()
    assert await found() == {"k1": "PAY-1"}
