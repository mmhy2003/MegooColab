"""A freestyle chat's agent creates tasks on the chat's own project (create_task with its run token)."""

from sqlalchemy import select

from app.tasks.models import Task, TaskEvent
from tests.chats.helpers import start, world
from tests.chats.test_chat_workflow import _round
from tests.factories import make_project
from tests.mcp.test_workflow_tools import _run_token, _tool
from tests.workflow.test_engine import _runs

DESCRIPTION = "Deliveries that fail are retried three times.\n\nOpen: the backoff."


async def _freestyle_run(client, db, mode="freestyle"):
    w = await world(client, db)
    chat = await start(client, mode=mode)
    rnd = await _round(db, chat)
    [run] = await _runs(rnd.id)
    return w, chat, rnd, run


async def test_freestyle_agent_creates_a_task_on_its_own_project(client, db, tc_factory):
    w, chat, rnd, run = await _freestyle_run(client, db)
    tc = tc_factory(lifespan=True)
    err, out = _tool(tc, await _run_token(run), "create_task", project_key="PAY", title="Retry webhook deliveries",
                     description_md=DESCRIPTION, assignee_agent_id=w.agent["id"])
    assert not err, out
    task = (await db.execute(select(Task).where(Task.title == "Retry webhook deliveries"))).scalar_one()
    assert task.project_id == rnd.project_id and not task.in_chat and task.chat_id is None
    assert task.assignee_agent_id is None and task.assignee_user_id is None  # nobody: it's reviewed first
    assert task.description_md.startswith(DESCRIPTION)
    assert task.description_md.rstrip().endswith(f"From chat: [{chat['title']}](/chats/{chat['id']})")
    [event] = (await db.execute(select(TaskEvent).where(TaskEvent.task_id == rnd.id,
                                                         TaskEvent.kind == "agent_task_created"))).scalars().all()
    assert event.actor_user_id is None and event.data["key"] == out["key"] and event.data["title"] == task.title
    assert event.data["agent_id"] == w.agent["id"]


async def test_freestyle_agent_cannot_create_on_another_project(client, db, tc_factory):
    w, _chat, _rnd, run = await _freestyle_run(client, db)
    await make_project(client, db, "OPS", w.owner)
    tc = tc_factory(lifespan=True)
    err, text = _tool(tc, await _run_token(run), "create_task", project_key="OPS", title="Elsewhere")
    assert err and "wrong_project" in text


async def test_other_runs_still_cannot_create_tasks(client, db, tc_factory):
    _w, _chat, _rnd, run = await _freestyle_run(client, db, mode="workflow")
    tc = tc_factory(lifespan=True)
    err, text = _tool(tc, await _run_token(run), "create_task", project_key="PAY", title="Nope")
    assert err and "not_allowed_in_role" in text
