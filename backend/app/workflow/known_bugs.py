"""Bug tasks for the known failing tests a finish reported (MC-100): a person asks for one per test from the
workflow panel, and a test that already has an open bug in the project links to it instead. One bug per test,
matched on `tasks.failing_test`. Workflow runs never create them (as follow_ups)."""

import re
import uuid

from sqlalchemy import select

from app.projects.models import BoardColumn, ColumnCategory
from app.tasks.models import Task
from app.tasks.visibility import on_board

# ":42" or ":42:5" right after a file extension: Playwright's position, which moves when the file is edited above it
_POSITION = re.compile(r"(\.[A-Za-z0-9]{1,10}):\d+(?::\d+)?(?!\w)")


def test_key(name: str) -> str:
    """The match key of a reported test name: whitespace collapsed, a position after a file name removed."""
    return _POSITION.sub(r"\1", " ".join(name.split()))


async def open_bugs(db, project_id: uuid.UUID, keys) -> dict[str, Task]:
    """The open bug of each key: on the board, not in a Done column. Of several, the lowest number."""
    keys = set(keys)
    if not keys:
        return {}
    rows = await db.execute(
        select(Task).join(BoardColumn, BoardColumn.id == Task.column_id)
        .where(Task.project_id == project_id, Task.failing_test.in_(keys), on_board(),
               BoardColumn.category != ColumnCategory.done)
        .order_by(Task.number)
    )
    found: dict[str, Task] = {}
    for t in rows.scalars():
        found.setdefault(t.failing_test, t)
    return found
