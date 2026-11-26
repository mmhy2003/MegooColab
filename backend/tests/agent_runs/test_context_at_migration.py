"""The migration that lets a run mark where its Knowledge Base and Memory sections go (MC-215)."""

import importlib.util
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal


def _load_migration():
    [path] = (Path(__file__).parents[2] / "migrations" / "versions").glob("*_agent_run_context_at.py")
    spec = importlib.util.spec_from_file_location("agent_run_context_at", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_follows_the_previous_head():
    assert _load_migration().down_revision == "d7b824108d6d"


async def test_context_at_is_a_nullable_integer(db):
    async with SessionLocal() as s:
        row = (await s.execute(text(
            "SELECT is_nullable, data_type FROM information_schema.columns "
            "WHERE table_name = 'agent_runs' AND column_name = 'context_at'"
        ))).one()
    assert (row.is_nullable, row.data_type) == ("YES", "integer")
