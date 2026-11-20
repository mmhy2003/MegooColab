"""Bug tasks for the known failing tests a finish reported (MC-100)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.auth.models import Role
from app.core.db import SessionLocal
from app.projects.models import BoardColumn, ColumnCategory
from app.tasks.models import Task, TaskLink
from app.tasks.schemas import TaskCreate, TaskOut, TaskUpdate
from app.workflow import known_bugs
from app.workflow.models import Stage, TaskWorkflow, WorkflowStatus, WorkflowTestRun
from tests.chats.helpers import start, world
from tests.chats.test_chat_workflow import _round
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


# ---- creating a bug (step 3) -----------------------------------------------------------------------------------

def _seen_on() -> str:
    return datetime.now(UTC).date().isoformat()


async def test_creates_a_bug_for_a_base_failure(client, db):
    pay, manager, _ = await make_project(client, db, "PAY")
    t = await _task(client)
    await _finished(t, [NEW, BASE, FLAKY])
    r = await _create(client, t["key"], BASE["name"])
    assert r.status_code == 200, r.text

    [bug] = await _bugs()
    n = int(t["key"].split("-")[1])
    assert (bug.type, bug.assignee_user_id, bug.assignee_agent_id, bug.parent_id, bug.reporter_id) == (
        "bug", None, None, None, manager.id)
    async with SessionLocal() as s:
        first = await s.scalar(select(BoardColumn.id).where(
            BoardColumn.project_id == uuid.UUID(pay["id"]), BoardColumn.category == ColumnCategory.before,
        ).order_by(BoardColumn.position).limit(1))
    assert bug.column_id == first
    assert bug.title == "Failing test: e2e/a.spec.ts:42:5 › finishes a task"
    assert bug.failing_test == "e2e/a.spec.ts › finishes a task"
    expected = known_bugs.description(name=BASE["name"], kind="base", source=f"[PAY-{n}](/projects/PAY/tasks/{n})",
                                      start_branch="develop", seen_on=_seen_on(), command=None)
    assert bug.description_md == expected
    assert expected.startswith(
        "This test already failed on the commit that [PAY-1](/projects/PAY/tasks/1) started from, on `develop`.")
    assert "- Command:" not in expected
    async with SessionLocal() as s:
        [link] = (await s.execute(select(TaskLink).where(TaskLink.target_id == bug.id))).scalars().all()
    assert (link.source_id, link.kind) == (uuid.UUID(t["id"]), "relates")
    [event] = await _events(uuid.UUID(t["id"]), "finish.bug_created")
    assert event.actor_user_id == manager.id
    assert event.data == {"key": f"PAY-{bug.number}", "title": bug.title, "task_id": str(bug.id),
                          "name": BASE["name"], "kind": "base"}


async def test_flaky_title_and_command_line(client, db):
    await make_project(client, db, "PAY")
    t = await _task(client)
    await _finished(t, [NEW, BASE, FLAKY])
    tid, now = uuid.UUID(t["id"]), datetime.now(UTC)
    async with SessionLocal() as s:
        for i, (stage, command, on_base) in enumerate((
            ("done", "pytest -x", False), ("done", "make test", False), ("done", "base run", True),
            ("build", "build run", False),
        )):
            s.add(WorkflowTestRun(task_id=tid, stage=stage, command=command, passed=False, failing=[FLAKY["name"]],
                                  on_base=on_base, created_at=now + timedelta(seconds=i)))
        await s.commit()
    r = await _create(client, t["key"], FLAKY["name"])
    assert r.status_code == 200, r.text
    [bug] = await _bugs()
    assert bug.title == "Flaky test: tests/x.py::test_y"
    assert bug.description_md.startswith(
        "This test failed and then passed when it was run again at the finish of [PAY-")
    assert "- Command: `make test`" in bug.description_md

    t2 = await _task(client, "Other")
    await _finished(t2, [BASE], start_branch=None)
    r = await _create(client, t2["key"], BASE["name"])
    assert r.status_code == 200, r.text
    [_, base_bug] = await _bugs()
    assert "on the start branch." in base_bug.description_md


async def test_no_duplicates(client, db):
    await make_project(client, db, "PAY")
    t = await _task(client)
    await _finished(t, [NEW, BASE, FLAKY])
    for _ in range(2):
        r = await _create(client, t["key"], BASE["name"])
        assert r.status_code == 200, r.text
    assert len(await _bugs()) == 1
    assert len(await _events(uuid.UUID(t["id"]), "finish.bug_created")) == 1

    t2 = await _task(client, "Other")
    moved = {"name": "e2e/a.spec.ts:57:5 › finishes a task", "kind": "base"}
    await _finished(t2, [moved])
    r = await _create(client, t2["key"], moved["name"])
    assert r.status_code == 200, r.text
    assert len(await _bugs()) == 1
    assert await _events(uuid.UUID(t2["id"]), "finish.bug_created") == []

    shop, _, _ = await make_project(client, db, "SHOP")
    s1 = await _task(client, "Shop task", project="SHOP")
    await _finished(s1, [BASE])
    r = await _create(client, s1["key"], BASE["name"])
    assert r.status_code == 200, r.text
    bugs = await _bugs()
    assert len(bugs) == 2
    assert {b.project_id for b in bugs} == {bugs[0].project_id, uuid.UUID(shop["id"])}


async def test_offered_again_after_done_or_delete(client, db):
    await make_project(client, db, "PAY")
    t = await _task(client)
    await _finished(t, [NEW, BASE, FLAKY])
    assert (await _create(client, t["key"], BASE["name"])).status_code == 200
    [first] = await _bugs()
    await _to_done(first.id)

    assert (await _create(client, t["key"], BASE["name"])).status_code == 200
    bugs = await _bugs()
    assert len(bugs) == 2
    second = bugs[1]
    r = await client.delete(f"/api/tasks/PAY-{second.number}")
    assert r.status_code == 204, r.text

    assert (await _create(client, t["key"], BASE["name"])).status_code == 200
    assert len(await _events(uuid.UUID(t["id"]), "finish.bug_created")) == 3


async def test_refusals(client, db):
    viewer = await make_user(db, role=Role.viewer)
    await make_project(client, db, "PAY", viewer)
    t = await _task(client)
    await _finished(t, [NEW, BASE, FLAKY])
    for name in (NEW["name"], "no such test"):
        r = await _create(client, t["key"], name)
        assert (r.status_code, r.json()["detail"]) == (409, "failure_not_listed")
    bare = await _task(client, "No workflow")
    r = await _create(client, bare["key"], BASE["name"])
    assert (r.status_code, r.json()["detail"]) == (409, "failure_not_listed")
    await login(client, viewer)
    r = await _create(client, t["key"], BASE["name"])
    assert (r.status_code, r.json()["detail"]) == (403, "forbidden")
    assert await _bugs() == []


async def test_the_task_itself_is_the_bug(client, db):
    await make_project(client, db, "PAY")
    t = await _task(client)
    async with SessionLocal() as s:
        await s.execute(update(Task).where(Task.id == uuid.UUID(t["id"]))
                        .values(failing_test=known_bugs.test_key(FLAKY["name"])))
        await s.commit()
    await _finished(t, [FLAKY])
    r = await _create(client, t["key"], FLAKY["name"])
    assert r.status_code == 200, r.text
    assert [b.id for b in await _bugs()] == [uuid.UUID(t["id"])]
    async with SessionLocal() as s:
        assert len((await s.execute(select(Task.id))).all()) == 1


async def test_chat_round(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await _finished({"id": str(rnd.id)}, [BASE])
    r = await _create(client, chat["rounds"][0]["key"], BASE["name"])
    assert r.status_code == 200, r.text
    [bug] = await _bugs()
    assert (bug.chat_id, bug.in_chat) == (None, False)
    async with SessionLocal() as s:
        assert (await s.execute(select(TaskLink).where(TaskLink.source_id == rnd.id))).first() is None
    assert f"(/chats/{chat['id']})" in bug.description_md
