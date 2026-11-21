"""Task events write pending firings from the board, the workflow and chats; triggered chats never fire."""

import dataclasses
import uuid

from sqlalchemy import delete, inspect, select, update

from app.mcp_server.auth import current_run
from app.projects.models import BoardColumn, ColumnCategory, Project, ProjectStatus
from app.tasks import service as tasks
from app.tasks.models import Task
from app.tasks.schemas import MoveIn, TaskCreate
from app.triggers import emit, events
from app.triggers.models import FiringStatus, Trigger, TriggerFiring
from app.workflow import engine
from tests.chats.helpers import start
from tests.chats.test_chat_workflow import _round
from tests.factories import login
from tests.triggers.helpers import make_trigger
from tests.workflow.test_engine import _runs

ALL_TYPES = {"task_types": ["story", "task", "bug"]}


async def _firings(db, trigger: Trigger) -> list[TriggerFiring]:
    [trigger_id] = inspect(trigger).identity  # no load: the trigger may be expired
    db.expire_all()
    return list((await db.execute(
        select(TriggerFiring).where(TriggerFiring.trigger_id == trigger_id).order_by(TriggerFiring.created_at)
    )).scalars())


async def _columns(client) -> dict[str, str]:
    r = await client.get("/api/projects/PAY/columns")
    assert r.status_code == 200, r.text
    return {c["name"]: c["id"] for c in r.json()}


async def _task(client, title: str, **body) -> dict:
    r = await client.post("/api/projects/PAY/tasks", json={"title": title, **body})
    assert r.status_code == 201, r.text
    return r.json()


async def _move(client, task: dict, column_id: str) -> None:
    r = await client.post(f"/api/tasks/{task['key']}/move", json={"column_id": column_id})
    assert r.status_code == 200, r.text


async def test_creating_a_task_writes_a_pending_firing(client, db, world):
    await login(client, world.manager)
    r = await client.post("/api/projects/PAY/labels", json={"name": "backend", "color": "#112233"})
    label = r.json()["id"]
    bugs = await make_trigger(db, world, "task_created", {"task_types": ["bug"], "label_id": label})
    every = await make_trigger(db, world, "task_created", ALL_TYPES)

    bug = await _task(client, "Login crashes", type="bug", label_ids=[label], description_md="Stack trace here")
    [firing] = await _firings(db, bugs)
    assert firing.status == FiringStatus.pending and firing.event == "task_created"
    assert firing.subject == {"kind": "task", "label": bug["key"], "title": "Login crashes",
                              "link": f"/projects/PAY/tasks/{bug['number']}", "note": "created"}
    assert f'Task {bug["key"]} "Login crashes"' in firing.what and "Stack trace here" in firing.what
    assert "Event: created by" in firing.what

    await _task(client, "No label", type="bug")  # the label does not match
    await _task(client, "A story", type="story", label_ids=[label])  # the type does not match
    assert len(await _firings(db, bugs)) == 1
    await _task(client, "A subtask", type="subtask", parent_id=bug["id"])
    assert len(await _firings(db, every)) == 3  # the bug, the unlabelled bug and the story; never the subtask


async def test_moving_to_done_fires_moved_and_finished(client, db, world):
    await login(client, world.manager)
    manager = world.manager.name
    cols = await _columns(client)
    to_do =await make_trigger(db, world, "task_moved", ALL_TYPES | {"column_id": cols["To Do"]})
    to_done = await make_trigger(db, world, "task_moved", ALL_TYPES | {"column_id": cols["Done"]})
    finished = await make_trigger(db, world, "task_finished", ALL_TYPES)
    task = await _task(client, "Ship it")

    await _move(client, task, cols["To Do"])  # between two columns that are not Done
    [moved] = await _firings(db, to_do)
    assert moved.subject["note"] == "moved to To Do" and "moved from Backlog to To Do" in moved.what
    assert await _firings(db, finished) == []

    await _move(client, task, cols["Done"])
    assert len(await _firings(db, to_done)) == 1
    [done] = await _firings(db, finished)
    assert done.subject["note"] == "finished" and f"Event: finished by {manager}" in done.what

    await _move(client, task, cols["Done"])  # within the column: no move
    assert len(await _firings(db, to_done)) == 1 and len(await _firings(db, finished)) == 1


async def test_the_workflow_finishing_a_task_fires_finished(client, db, world):
    await login(client, world.manager)
    finished = await make_trigger(db, world, "task_finished", ALL_TYPES)
    created = await _task(client, "Done by the agent")
    task = await db.get(Task, uuid.UUID(created["id"]))
    await engine.move_to_category(db, task, ColumnCategory.done)
    await db.commit()
    [firing] = await _firings(db, finished)
    assert "Event: finished by the workflow" in firing.what


async def test_epic_completed_fires_only_with_the_last_task(client, db, world):
    await login(client, world.manager)
    cols = await _columns(client)
    completed = await make_trigger(db, world, "epic_completed")
    epic = await _task(client, "Payments v2", type="epic")
    first = await _task(client, "Card form", type="story", parent_id=epic["id"])
    last = await _task(client, "Refunds", type="bug", parent_id=epic["id"])

    await _move(client, first, cols["Done"])
    assert await _firings(db, completed) == []
    await _move(client, last, cols["Done"])
    [firing] = await _firings(db, completed)
    assert firing.subject["label"] == epic["key"] and firing.subject["note"] == "completed"
    assert f'{last["key"]} "Refunds" was the last to finish' in firing.what

    await _move(client, last, cols["To Do"])  # reopened, then finished again
    await _move(client, last, cols["Done"])
    assert len(await _firings(db, completed)) == 2


async def test_paused_trigger_and_closed_project_write_nothing(client, db, world):
    await login(client, world.manager)
    paused = await make_trigger(db, world, "task_created", ALL_TYPES, paused=True)
    active = await make_trigger(db, world, "task_created", ALL_TYPES)
    await _task(client, "One")
    assert await _firings(db, paused) == [] and len(await _firings(db, active)) == 1

    created = await _task(client, "Two")
    await db.execute(delete(TriggerFiring))
    await db.execute(update(Project).where(Project.key == "PAY").values(status=ProjectStatus.finished))
    await db.commit()
    await emit.task_created(db, await db.get(Task, uuid.UUID(created["id"])), world.manager)
    await db.commit()
    assert await _firings(db, active) == []


async def test_chat_rounds_never_fire_but_adding_one_to_the_board_does(client, db, world):
    created = await make_trigger(db, world, "task_created", {"task_types": ["story", "task", "bug"]})
    chat = await start(client)  # as the laptop agent's owner
    assert await _firings(db, created) == []
    assert (await client.post(f"/api/chats/{chat['id']}/end")).status_code == 200
    r = await client.post(f"/api/chats/{chat['id']}/rounds/1/board", json={"add": True})
    assert r.status_code == 200, r.text
    [firing] = await _firings(db, created)
    assert firing.subject["label"] == f"PAY-{(await _round(db, chat)).number}"


async def _to_do(db, project: Project) -> BoardColumn:
    return await db.scalar(select(BoardColumn).where(BoardColumn.project_id == project.id, BoardColumn.name == "To Do"))


async def _act(db, w, project: Project, title: str) -> None:
    """The manager creates a task and moves it to To Do, through the task service."""
    await db.refresh(w.manager)
    await db.refresh(project)
    task = await tasks.create_task(db, w.manager, project, TaskCreate(title=title))
    to_do = await _to_do(db, project)
    await tasks.move_task(db, w.manager, project, task, MoveIn(column_id=to_do.id))
    await db.commit()


async def test_loop_guard(client, db, world):
    created = await make_trigger(db, world, "task_created", ALL_TYPES)
    project = await db.get(Project, uuid.UUID(world.project["id"]))
    moved = await make_trigger(db, world, "task_moved", ALL_TYPES | {"column_id": str((await _to_do(db, project)).id)})
    triggered = await start(client, mode="freestyle")
    person = await start(client, "Tidy the board", mode="freestyle")
    db.add(TriggerFiring(trigger_id=created.id, event="task_created", subject={}, what="",
                         status=FiringStatus.started, chat_id=uuid.UUID(triggered["id"])))
    await db.commit()

    def count(rows):
        return len([f for f in rows if f.chat_id is None])

    [run] = await _runs((await _round(db, triggered)).id)
    token = current_run.set(run)
    try:
        await _act(db, world, project, "From the triggered chat")
    finally:
        current_run.reset(token)
    assert count(await _firings(db, created)) == 0 and await _firings(db, moved) == []

    token = tasks.event_origin.set({"id": triggered["id"], "title": "x"})
    try:
        await _act(db, world, project, "Through the board tools")
    finally:
        tasks.event_origin.reset(token)
    assert count(await _firings(db, created)) == 0 and await _firings(db, moved) == []

    [run] = await _runs((await _round(db, person)).id)
    token = current_run.set(run)
    try:
        await _act(db, world, project, "From a person's chat")
    finally:
        current_run.reset(token)
    assert count(await _firings(db, created)) == 1 and len(await _firings(db, moved)) == 1


async def test_a_failing_emit_never_fails_the_action(client, db, world, monkeypatch, caplog):
    async def broken(db, payload):
        raise RuntimeError("describe failed")

    monkeypatch.setitem(events.REGISTRY, "task_created",
                        dataclasses.replace(events.REGISTRY["task_created"], describe=broken))
    created = await make_trigger(db, world, "task_created", ALL_TYPES)
    await login(client, world.manager)
    task = await _task(client, "Still created")
    assert await db.get(Task, uuid.UUID(task["id"])) is not None
    assert await _firings(db, created) == []
    assert "triggers: emit failed" in caplog.text
