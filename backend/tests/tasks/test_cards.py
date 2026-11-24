"""cards.show stores a validated card on a task or chat round, and of_runs reads each run's cards (MC-173)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.a2ui.service import CardError
from app.agent_runs.models import AgentRun
from app.auth.models import User
from app.chats.models import Chat
from app.core.db import SessionLocal
from app.tasks import cards
from app.tasks.models import Task, TaskCard
from tests.chats.helpers import start, world
from tests.workflow.test_freestyle_engine import _freestyle

CARD = json.loads((Path(cards.__file__).parents[1] / "a2ui" / "card_example.json").read_text())


async def _show(task_id, run_id, user_id, title="Test results", text="412 passed, 3 failed.", card=CARD) -> TaskCard:
    async with SessionLocal() as s:
        run = await s.get(AgentRun, run_id) if run_id else None
        row = await cards.show(s, await s.get(Task, task_id), run, await s.get(User, user_id), title, text, card)
        await s.commit()
        return row


async def _count(task_id) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(TaskCard).where(TaskCard.task_id == task_id))


async def test_show_stores_the_card(client, db):
    w, task_id, run = await _freestyle(client, db)
    row = await _show(task_id, run.id, w.owner.id, title=" Test results ")
    async with SessionLocal() as s:
        stored = await s.get(TaskCard, row.id)
    assert stored.task_id == task_id and stored.run_id == run.id
    assert stored.agent_id == run.agent_id and stored.user_id is None
    assert stored.title == "Test results" and stored.text == "412 passed, 3 failed."
    assert stored.surface["createSurface"]["surfaceId"].startswith("card-")


async def test_show_for_a_personal_token(client, db):
    w, task_id, _ = await _freestyle(client, db)
    row = await _show(task_id, None, w.owner.id)
    assert row.user_id == w.owner.id and row.agent_id is None and row.run_id is None


async def test_show_publishes_task_updated(client, db, monkeypatch):
    w, task_id, run = await _freestyle(client, db)
    published = []

    async def spy(db_, event):
        published.append(event)

    monkeypatch.setattr(cards, "publish", spy)
    await _show(task_id, run.id, w.owner.id)
    assert [(e.type, e.task_id) for e in published] == [("task.updated", task_id)]


async def test_show_touches_the_chat(client, db):
    w = await world(client, db)
    chat = await start(client)
    chat_id = uuid.UUID(chat["id"])
    async with SessionLocal() as s:
        task = await s.scalar(select(Task).where(Task.chat_id == chat_id))
        before = datetime.now(UTC) - timedelta(days=1)
        (await s.get(Chat, chat_id)).last_activity_at = before
        await s.commit()
    await _show(task.id, None, w.owner.id)
    async with SessionLocal() as s:
        assert (await s.get(Chat, chat_id)).last_activity_at > before


@pytest.mark.parametrize("field, value, code", [
    ("title", "", "invalid_card"), ("title", "  ", "invalid_card"), ("title", "t" * 121, "too_large"),
    ("text", "", "invalid_card"), ("text", "  ", "invalid_card"), ("text", "t" * 501, "too_large"),
])
async def test_empty_or_long_title_and_text(client, db, field, value, code):
    w, task_id, run = await _freestyle(client, db)
    with pytest.raises(CardError) as e:
        await _show(task_id, run.id, w.owner.id, **{field: value})
    assert e.value.code == code and e.value.problems[0]["path"] == field
    assert await _count(task_id) == 0


async def test_three_cards_per_run(client, db):
    w, task_id, run = await _freestyle(client, db)
    for _ in range(cards.MAX_PER_RUN):
        await _show(task_id, run.id, w.owner.id)
    with pytest.raises(CardError) as e:
        await _show(task_id, run.id, w.owner.id)
    assert e.value.code == "too_many_cards"
    await _show(task_id, None, w.owner.id)
    assert await _count(task_id) == cards.MAX_PER_RUN + 1


async def test_hundred_cards_per_task(client, db):
    w, task_id, run = await _freestyle(client, db)
    async with SessionLocal() as s:
        s.add_all(TaskCard(task_id=task_id, user_id=w.owner.id, title="t", text="t", surface={})
                  for _ in range(cards.MAX_PER_TASK))
        await s.commit()
    with pytest.raises(CardError) as e:
        await _show(task_id, run.id, w.owner.id)
    assert e.value.code == "too_many_cards"
    assert await _count(task_id) == cards.MAX_PER_TASK


async def test_invalid_card_stores_nothing(client, db):
    w, task_id, run = await _freestyle(client, db)
    card = {"components": [{"id": "root", "component": "TextField", "label": "Name", "value": {"path": "/name"}}]}
    with pytest.raises(CardError) as e:
        await _show(task_id, run.id, w.owner.id, card=card)
    assert e.value.code == "card_with_inputs"
    assert await _count(task_id) == 0


async def test_of_runs_groups_by_run_oldest_first(client, db):
    w, task_id, first = await _freestyle(client, db)
    async with SessionLocal() as s:
        second = AgentRun(task_id=task_id, agent_id=first.agent_id, policy="workspace", prompt="p", status="completed")
        s.add(second)
        await s.commit()
    t0 = datetime.now(UTC)
    rows = [(first.id, "b", t0 + timedelta(seconds=2)), (second.id, "c", t0 + timedelta(seconds=1)),
            (first.id, "a", t0), (None, "mine", t0)]
    async with SessionLocal() as s:
        s.add_all(TaskCard(task_id=task_id, run_id=run_id, title=title, text="t", surface={}, created_at=at)
                  for run_id, title, at in rows)
        await s.commit()
        got = await cards.of_runs(s, [first.id, second.id])
        assert await cards.of_runs(s, []) == {}
    assert {run_id: [c.title for c in rows] for run_id, rows in got.items()} == {first.id: ["a", "b"], second.id: ["c"]}
