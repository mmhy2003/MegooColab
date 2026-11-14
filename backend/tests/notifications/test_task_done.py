"""A task reaching Done: whoever it is assigned to (for an agent, its owner) hears it as task_done, everyone else on the
project's teams as team_task_done. Never the person who moved it; once per move into Done."""

import uuid

from sqlalchemy import update

from app.core.db import SessionLocal
from app.notifications.jobs import KIND_LOOK
from app.notifications.models import DEFAULT_PREFS, Kind
from app.tasks.models import Task
from app.workflow import engine
from tests.chats.test_freestyle_board import _setup as _freestyle_setup
from tests.chats.test_freestyle_board import _task as _plain_task
from tests.mcp.test_workflow_tools import _tool
from tests.notifications.test_core import _rows
from tests.notifications.test_triggers import _read_all
from tests.workflow.test_engine import _board, _member, _move


async def _done_rows(user_id) -> list:
    return [n for n in await _rows(user_id) if n.kind in ("task_done", "team_task_done")]


async def _workflow_moves(task_id: uuid.UUID, category: str) -> None:
    async with SessionLocal() as s:
        task = await s.get(Task, task_id)
        await engine.move_to_category(s, task, category)
        await s.commit()


async def test_a_person_moving_a_task_to_done_tells_the_team_but_not_themselves(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    member = await _member(db, tc)
    assert _move(tc, b.key, b.cols["done"]).status_code == 200
    assert await _done_rows(b.manager.id) == []  # the manager moved it (and owns its agent)
    [n] = await _done_rows(member.id)
    assert (n.kind, n.task_id, n.link) == ("team_task_done", b.task_id, f"/projects/PAY/board?task={b.key}")
    assert n.title == f"{b.key} is done"
    assert n.body == f"Fix login — moved to Done by {b.manager.name}"


async def test_the_workflow_finishing_tells_the_agents_owner_once_and_the_team(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    member = await _member(db, tc)
    await _workflow_moves(b.task_id, "done")
    [mine] = await _done_rows(b.manager.id)  # the owner is on the team too: one notification, as the owner
    assert mine.kind == "task_done" and mine.title == f"{b.key} is done"
    assert mine.body == "Fix login — moved to Done when its workflow finished"
    [theirs] = await _done_rows(member.id)
    assert theirs.kind == "team_task_done" and theirs.body == mine.body


async def test_a_task_assigned_to_a_person_tells_them_as_their_own(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    member = await _member(db, tc)
    await db.execute(update(Task).where(Task.id == b.task_id).values(assignee_user_id=member.id,
                                                                      assignee_agent_id=None))
    await db.commit()
    await _workflow_moves(b.task_id, "done")
    assert [n.kind for n in await _done_rows(member.id)] == ["task_done"]
    assert [n.kind for n in await _done_rows(b.manager.id)] == ["team_task_done"]  # no longer their agent's


async def test_only_a_move_into_done_tells_and_each_one_does(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    member = await _member(db, tc)
    key = tc.post("/api/projects/PAY/tasks", json={"title": "Plain"}).json()["key"]  # no workflow to start
    assert _move(tc, key, b.cols["working"]).status_code == 200
    assert await _done_rows(member.id) == []
    assert _move(tc, key, b.cols["done"]).status_code == 200
    assert len(await _done_rows(member.id)) == 1
    second_done = tc.post("/api/projects/PAY/columns", json={"name": "Shipped", "category": "done"})
    assert second_done.status_code == 201, second_done.text
    assert _move(tc, key, second_done.json()).status_code == 200  # from Done to Done: still done
    assert len(await _done_rows(member.id)) == 1
    await _read_all(member.id)
    assert _move(tc, key, b.cols["working"]).status_code == 200  # reopened, then done again
    assert _move(tc, key, b.cols["done"]).status_code == 200
    assert len(await _done_rows(member.id)) == 2


async def test_a_chats_agent_moving_a_task_to_done_tells_its_owner(client, db, tc_factory):
    w, _chat, _rnd, tc, token = await _freestyle_setup(client, db, tc_factory)
    task = await _plain_task(client, "Card retries time out")
    err, out = _tool(tc, token, "move_task", key=task["key"], column="Done")
    assert not err, out
    # the run's token acts with its owner's rights, but the agent moved it: the owner hears
    [mine] = await _done_rows(w.owner.id)
    assert mine.kind == "team_task_done"
    assert mine.body == "Card retries time out — moved to Done by laptop-claude (your agent)"
    [theirs] = await _done_rows(w.other.id)
    assert theirs.body == "Card retries time out — moved to Done by laptop-claude"


def test_defaults_and_email_look():
    assert DEFAULT_PREFS[Kind.task_done] == (True, True, False, False)
    assert DEFAULT_PREFS[Kind.team_task_done] == (True, False, False, False)
    assert KIND_LOOK["task_done"][0] == "Done" and KIND_LOOK["team_task_done"][0] == "Done"
