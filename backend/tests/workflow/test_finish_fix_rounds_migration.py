"""The migration that adds task_workflows.finish_fix_rounds, the finish's fix rounds (MC-98)."""

import importlib.util
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal


def _load_migration():
    [path] = (Path(__file__).parents[2] / "migrations" / "versions").glob("*_finish_fix_rounds.py")
    spec = importlib.util.spec_from_file_location("finish_fix_rounds", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_follows_the_finish_test_failures_migration():
    assert _load_migration().down_revision == "dc77635edebb"


async def test_the_column_is_not_nullable_and_defaults_to_zero(db):
    async with SessionLocal() as s:
        row = (await s.execute(text(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'task_workflows' AND column_name = 'finish_fix_rounds'"
        ))).one()
    assert row.is_nullable == "NO"
    assert "0" in row.column_default
