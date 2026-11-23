"""The migration that lets a question hold an A2UI form and the data it was answered with (MC-172)."""

import importlib.util
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal


def _load_migration():
    [path] = (Path(__file__).parents[2] / "migrations" / "versions").glob("*_question_forms.py")
    spec = importlib.util.spec_from_file_location("question_forms", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_follows_the_previous_head():
    assert _load_migration().down_revision == "c9c633676147"


async def _column(table: str, column: str):
    async with SessionLocal() as s:
        return (await s.execute(text(
            "SELECT is_nullable, data_type FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ), {"table": table, "column": column})).one()


async def test_form_and_answer_data_are_nullable_jsonb(db):
    for column in ("form", "answer_data"):
        row = await _column("workflow_questions", column)
        assert (row.is_nullable, row.data_type) == ("YES", "jsonb"), column
