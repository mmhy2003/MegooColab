"""The migration that adds task_cards, the cards agents show in a task's or chat's thread (MC-173)."""

import importlib.util
import uuid
from pathlib import Path

from sqlalchemy import select, text

from app.agent_runs.models import AgentRun
from app.agents.models import Agent, AgentProgram
from app.core.db import SessionLocal
from app.projects.models import BoardColumn, Project
from app.tasks.models import Task, TaskCard
from tests.factories import make_project


def _load_migration():
    [path] = (Path(__file__).parents[2] / "migrations" / "versions").glob("*_task_cards.py")
    spec = importlib.util.spec_from_file_location("task_cards", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_follows_the_previous_head():
    assert _load_migration().down_revision == "32e547118527"


async def test_task_cards_columns(db):
    async with SessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT column_name, is_nullable, data_type, character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'task_cards'"
        ))).all()
    columns = {r.column_name: (r.is_nullable, r.data_type, r.character_maximum_length) for r in rows}
    assert columns["title"] == ("NO", "character varying", 120)
    assert columns["text"] == ("NO", "text", None)
    assert columns["surface"] == ("NO", "jsonb", None)
    assert columns["task_id"] == ("NO", "uuid", None)
    for column in ("run_id", "agent_id", "user_id"):
        assert columns[column] == ("YES", "uuid", None), column
    assert columns["created_at"][:2] == ("NO", "timestamp with time zone")


async def test_task_cards_foreign_keys_are_named(db):
    async with SessionLocal() as s:
        names = set((await s.execute(text(
            "SELECT constraint_name FROM information_schema.table_constraints WHERE table_name = 'task_cards'"
        ))).scalars())
    assert {"task_cards_pkey", "task_cards_task_id_fkey", "task_cards_run_id_fkey", "task_cards_agent_id_fkey",
            "task_cards_user_id_fkey"} <= names


async def _task(client, db):
    project, manager, _ = await make_project(client, db, "PAY")
    project = await db.get(Project, uuid.UUID(project["id"]))
    col = (await db.execute(select(BoardColumn).where(BoardColumn.project_id == project.id).limit(1))).scalar_one()
    task = Task(project_id=project.id, number=1, type="task", title="Retry failed card payments", column_id=col.id,
                position=1.0)
    db.add(task)
    await db.commit()
    return task, manager


async def _card(db, task, **kw):
    card = TaskCard(task_id=task.id, title="Payments", text="3 tasks done.", surface={"version": "v1.0"}, **kw)
    db.add(card)
    await db.commit()
    return card.id


async def test_a_deleted_task_takes_its_cards(client, db):
    task, _ = await _task(client, db)
    card_id = await _card(db, task)
    await db.delete(task)
    await db.commit()
    db.expunge_all()
    assert await db.get(TaskCard, card_id) is None


async def test_a_deleted_run_leaves_its_card(client, db):
    task, manager = await _task(client, db)
    agent = Agent(owner_id=manager.id, name="Bot", program=AgentProgram.claude_code)
    db.add(agent)
    await db.flush()
    run = AgentRun(task_id=task.id, agent_id=agent.id, requested_by=manager.id, policy="workspace", prompt="p",
                   status="completed")
    db.add(run)
    await db.flush()
    card_id = await _card(db, task, run_id=run.id, agent_id=agent.id)
    await db.delete(run)
    await db.commit()
    db.expunge_all()
    card = await db.get(TaskCard, card_id)
    assert card is not None and card.run_id is None and card.agent_id == agent.id
