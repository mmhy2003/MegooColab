"""Chats on the dashboard: the Open chats tile, the Chats card, Needs you, Running now, and finished chats."""

from datetime import UTC, datetime

from sqlalchemy import update

from app.agent_runs.models import AgentRun, RunStatus
from app.tasks.models import Task
from app.workflow.models import Needs, TaskWorkflow, WorkflowStatus
from tests.chats.helpers import start, world
from tests.chats.test_chat_workflow import _round
from tests.factories import login


async def _dash(client) -> dict:
    r = await client.get("/api/dashboard")
    assert r.status_code == 200, r.text
    return r.json()


async def test_an_open_chat_shows_on_the_tile_and_the_card(client, db):
    await world(client, db)
    chat = await start(client)
    d = await _dash(client)
    assert d["numbers"]["open_chats"] == 1 and d["numbers"]["chats_waiting_on_you"] == 0
    assert [(c["id"], c["title"], c["project_key"]) for c in d["chats"]] == [(chat["id"], "Fix the empty email crash", "PAY")]


async def test_a_chat_waiting_on_you_is_in_needs_you_and_counted(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await db.execute(update(AgentRun).where(AgentRun.task_id == rnd.id).values(status=RunStatus.completed))
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == rnd.id).values(
        status=WorkflowStatus.waiting_human, needs=Needs.question, waiting_since=datetime.now(UTC),
    ))
    await db.commit()
    d = await _dash(client)
    assert d["numbers"]["chats_waiting_on_you"] == 1
    [need] = [n for n in d["needs"] if n.get("chat_id")]
    assert need["chat_id"] == chat["id"] and need["link"] == f"/chats/{chat['id']}"


async def test_chats_follow_who_can_see_them(client, client_factory, db):
    w = await world(client, db)
    await start(client)
    oc = client_factory()
    await login(oc, w.other)
    d = await _dash(oc)
    assert d["numbers"]["open_chats"] == 0 and d["chats"] == []


async def test_a_running_chat_round_is_tagged_in_running_now(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await db.execute(update(AgentRun).where(AgentRun.task_id == rnd.id).values(
        status=RunStatus.running, started_at=datetime.now(UTC),
    ))
    await db.commit()
    [item] = (await _dash(client))["running"]
    assert item["chat_id"] == chat["id"] and item["link"] == f"/chats/{chat['id']}"


async def test_a_finished_round_counts_as_a_chat_not_an_agent_task(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await db.execute(update(Task).where(Task.id == rnd.id).values(completed_at=datetime.now(UTC)))
    await db.commit()
    today = (await _dash(client))["finished_daily"][-1]
    assert (today["chats"], today["agents"], today["people"]) == (1, 0, 0)
