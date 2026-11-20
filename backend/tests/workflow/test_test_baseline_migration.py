"""The migration that adds the columns of the test baseline and its project setting (MC-99)."""

import importlib.util
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal


def _load_migration():
    [path] = (Path(__file__).parents[2] / "migrations" / "versions").glob("*_test_baseline.py")
    spec = importlib.util.spec_from_file_location("test_baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_follows_the_finish_fix_rounds_migration():
    assert _load_migration().down_revision == "87414f9affea"


async def _column(table: str, column: str):
    async with SessionLocal() as s:
        return (await s.execute(text(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ), {"table": table, "column": column})).one()


async def test_the_project_setting_is_not_nullable_and_defaults_to_true(db):
    row = await _column("projects", "record_test_baseline")
    assert row.is_nullable == "NO"
    assert "true" in row.column_default


async def test_the_baseline_flag_is_not_nullable_and_defaults_to_false(db):
    row = await _column("workflow_test_runs", "baseline")
    assert row.is_nullable == "NO"
    assert "false" in row.column_default


async def test_the_frozen_setting_is_nullable(db):
    row = await _column("task_workflows", "build_records_baseline")
    assert row.is_nullable == "YES"
