"""A freestyle chat's agent works on its own project's board: tasks, epics and sprints, with the agent owner's rights.
Every change is a line in the chat (agent_board_changed on the round) and, on the changed task, an event that links
back to the chat."""

import uuid

from sqlalchemy import select, update

from app.auth.models import Role, User
from app.core.db import SessionLocal
from app.sprints.models import Sprint, SprintState
from app.tasks.models import Task, TaskEvent
from app.workflow.models import RunRole
from tests.chats.test_freestyle_tasks import _freestyle_run
from tests.factories import make_project
from tests.mcp.test_workflow_tools import _run_token, _tool


async def _task(client, title: str, type_: str = "task") -> dict:
    r = await client.post("/api/projects/PAY/tasks", json={"title": title, "type": type_})
    assert r.status_code == 201, r.text
    return r.json()


async def _board_lines(rnd) -> list[dict]:
    async with SessionLocal() as s:
        rows = await s.execute(select(TaskEvent).where(TaskEvent.task_id == rnd.id, TaskEvent.kind == "agent_board_changed")
                               .order_by(TaskEvent.created_at, TaskEvent.id))
        return [e.data for e in rows.scalars()]


async def _events(task_id, kind: str) -> list[TaskEvent]:
    async with SessionLocal() as s:
        rows = await s.execute(select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.kind == kind))
        return list(rows.scalars())


async def _make_manager(user: User) -> None:
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == user.id).values(role=Role.manager))
        await s.commit()


async def _setup(client, db, tc_factory):
    w, chat, rnd, run = await _freestyle_run(client, db)
    return w, chat, rnd, tc_factory(lifespan=True), await _run_token(run)


async def test_reads_its_projects_tasks_and_epics(client, db, tc_factory):
    _w, _chat, _rnd, tc, token = await _setup(client, db, tc_factory)
    epic = await _task(client, "Checkout v2", "epic")
    await _task(client, "Card retries time out")
    err, rows = _tool(tc, token, "list_tasks", project_key="PAY")
    assert not err, rows
    assert {r["title"] for r in rows} >= {"Checkout v2", "Card retries time out"}
    assert all("Fix the empty email crash" not in r["title"] for r in rows)  # chat rounds are off the board
    err, rows = _tool(tc, token, "list_tasks", project_key="PAY", type="epic")
    assert not err and [r["key"] for r in rows] == [epic["key"]]
    err, out = _tool(tc, token, "get_task", key=epic["key"])
    assert not err and out["title"] == "Checkout v2"


async def test_changes_a_task_and_puts_it_under_an_epic(client, db, tc_factory):
    _w, chat, rnd, tc, token = await _setup(client, db, tc_factory)
    epic = await _task(client, "Checkout v2", "epic")
    task = await _task(client, "Card retries time out")
    err, out = _tool(tc, token, "update_task", key=task["key"], priority="high", story_points=3, epic_key=epic["key"])
    assert not err, out
    row = await db.get(Task, uuid.UUID(task["id"]))
    await db.refresh(row)
    assert (str(row.priority), row.story_points, str(row.parent_id)) == ("high", 3, epic["id"])
    lines = {line["action"]: line for line in await _board_lines(rnd)}  # one call: same moment, any order
    assert set(lines) == {"epic_set", "task_changed"} and {line["key"] for line in lines.values()} == {task["key"]}
    assert lines["epic_set"]["epic"] == epic["key"] and lines["epic_set"]["title"] == "Card retries time out"
    assert set(lines["task_changed"]["fields"]) == {"priority", "story_points"}
    # the task's own history links back to the chat
    changed = await _events(row.id, "field_changed")
    assert changed and all(e.data["chat"] == {"id": chat["id"], "title": chat["title"]} for e in changed)
    # and out of the epic again
    err, out = _tool(tc, token, "update_task", key=task["key"], epic_key="")
    assert not err, out
    await db.refresh(row)
    assert row.parent_id is None
    last = (await _board_lines(rnd))[-1]
    assert (last["action"], last["key"], last["epic"]) == ("epic_set", task["key"], None)


async def test_moves_a_task(client, db, tc_factory):
    _w, _chat, rnd, tc, token = await _setup(client, db, tc_factory)
    task = await _task(client, "Card retries time out")
    err, out = _tool(tc, token, "move_task", key=task["key"], column="done")
    assert not err, out
    [line] = await _board_lines(rnd)
    assert (line["action"], line["key"], line["column"]) == ("task_moved", task["key"], "Done")


async def test_deletes_a_task_but_never_its_own_chat_round(client, db, tc_factory):
    _w, _chat, rnd, tc, token = await _setup(client, db, tc_factory)
    task = await _task(client, "Card retries time out")
    err, out = _tool(tc, token, "delete_task", key=task["key"])
    assert not err, out
    assert (await db.execute(select(Task).where(Task.title == "Card retries time out"))).scalar_one_or_none() is None
    [line] = await _board_lines(rnd)
    assert (line["action"], line["key"], line["title"]) == ("task_deleted", task["key"], "Card retries time out")
    project_key = task["key"].split("-")[0]
    err, text = _tool(tc, token, "delete_task", key=f"{project_key}-{rnd.number}")
    assert err and "task_not_found" in text
    assert await db.get(Task, rnd.id) is not None


async def test_works_on_its_own_project_only(client, db, tc_factory):
    w, _chat, _rnd, tc, token = await _setup(client, db, tc_factory)
    await make_project(client, db, "OPS", w.owner)
    r = await client.post("/api/projects/OPS/tasks", json={"title": "Elsewhere"})
    key = r.json()["key"]
    for name, args in [("list_tasks", {"project_key": "OPS"}), ("get_task", {"key": key}),
                       ("update_task", {"key": key, "title": "x"}), ("move_task", {"key": key, "column": "Done"}),
                       ("delete_task", {"key": key}), ("list_sprints", {"project_key": "OPS"}),
                       ("create_sprint", {"project_key": "OPS", "name": "S", "start_date": "2026-11-16",
                                          "end_date": "2026-11-27"})]:
        err, text = _tool(tc, token, name, **args)
        assert err and "wrong_project" in text, (name, text)


async def test_plans_a_sprint_from_start_to_finish(client, db, tc_factory):
    w, _chat, rnd, tc, token = await _setup(client, db, tc_factory)
    await _make_manager(w.owner)
    task = await _task(client, "Card retries time out")
    err, sprint = _tool(tc, token, "create_sprint", project_key="PAY", name="Sprint 12", goal="Checkout v2",
                        start_date="2026-11-16", end_date="2026-11-27")
    assert not err, sprint
    err, out = _tool(tc, token, "set_task_sprint", key=task["key"], sprint="sprint 12")  # by name, any case
    assert not err, out
    assert [e.data["chat"]["id"] for e in await _events(uuid.UUID(task["id"]), "sprint_changed")]
    err, out = _tool(tc, token, "update_sprint", sprint=sprint["id"], name="Sprint 12b", end_date="2026-11-28")
    assert not err and out["name"] == "Sprint 12b"
    err, rows = _tool(tc, token, "list_sprints", project_key="PAY")
    assert not err and [r["name"] for r in rows] == ["Sprint 12b"]
    assert not _tool(tc, token, "start_sprint", sprint="Sprint 12b")[0]
    assert not _tool(tc, token, "complete_sprint", sprint="Sprint 12b")[0]
    async with SessionLocal() as s:
        assert (await s.get(Sprint, uuid.UUID(sprint["id"]))).state == SprintState.completed
    err, out = _tool(tc, token, "set_task_sprint", key=task["key"], sprint=None)
    assert not err, out
    assert not _tool(tc, token, "delete_sprint", sprint="Sprint 12b")[0]
    actions = [(line["action"], line.get("sprint")) for line in await _board_lines(rnd)]
    assert actions == [
        ("sprint_created", "Sprint 12"), ("sprint_set", "Sprint 12"), ("sprint_changed", "Sprint 12b"),
        ("sprint_started", "Sprint 12b"), ("sprint_completed", "Sprint 12b"), ("sprint_set", None),
        ("sprint_deleted", "Sprint 12b"),
    ]
    created = (await _board_lines(rnd))[0]
    assert (created["start"], created["end"]) == ("2026-11-16", "2026-11-27")
    assert created["project"] == "PAY"  # the chat line links to the project's sprints


async def test_sprints_need_the_owners_manage_rights(client, db, tc_factory):
    _w, _chat, _rnd, tc, token = await _setup(client, db, tc_factory)
    err, text = _tool(tc, token, "create_sprint", project_key="PAY", name="S", start_date="2026-11-16",
                      end_date="2026-11-27")
    assert err and "forbidden" in text


async def test_other_runs_cannot_change_the_board(client, db, tc_factory):
    _w, _chat, _rnd, run = await _freestyle_run(client, db, mode="workflow")
    tc = tc_factory(lifespan=True)
    token = await _run_token(run)
    for name, args in [("delete_task", {"key": "PAY-1"}), ("list_sprints", {"project_key": "PAY"}),
                       ("create_sprint", {"project_key": "PAY", "name": "S", "start_date": "2026-11-16",
                                          "end_date": "2026-11-27"}),
                       ("update_task", {"key": "PAY-1", "title": "x"})]:
        err, text = _tool(tc, token, name, **args)
        assert err and "not_allowed_in_role" in text, (name, text)


async def test_created_line_says_the_type(client, db, tc_factory):
    _w, _chat, rnd, tc, token = await _setup(client, db, tc_factory)
    err, out = _tool(tc, token, "create_task", project_key="PAY", title="Checkout v2", type="epic")
    assert not err, out
    [event] = await _events(rnd.id, "agent_task_created")
    assert event.data["type"] == "epic"


async def test_freestyle_prompt_covers_the_board(client, db):
    _w, _chat, rnd, _run = await _freestyle_run(client, db)
    from app.chats.context import freestyle_tasks_context

    section = await freestyle_tasks_context(db, rnd, RunRole.freestyle)
    assert section.startswith("## Working on the board")
    for tool in ("create_task", "update_task", "move_task", "delete_task", "list_tasks", "create_sprint",
                 "set_task_sprint", "start_sprint", "complete_sprint", "delete_sprint"):
        assert tool in section, tool
    assert "ask first" in section.lower() and "never assign" in section.lower()
    assert await freestyle_tasks_context(db, rnd, RunRole.brainstorm) is None
    from app.workflow import context

    assert freestyle_tasks_context in context.context_providers
