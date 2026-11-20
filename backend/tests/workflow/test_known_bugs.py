"""Bug tasks for the known failing tests a finish reported (MC-100)."""

from app.tasks.models import Task
from app.tasks.schemas import TaskCreate, TaskOut, TaskUpdate


def test_failing_test_is_a_column_no_api_field():
    col = Task.__table__.c.failing_test
    assert col.nullable and col.type.length == 300
    for schema in (TaskCreate, TaskUpdate, TaskOut):
        assert "failing_test" not in schema.model_fields
    [ix] = [i for i in Task.__table__.indexes if i.name == "ix_tasks_project_failing_test"]
    assert [c.name for c in ix.columns] == ["project_id", "failing_test"]
