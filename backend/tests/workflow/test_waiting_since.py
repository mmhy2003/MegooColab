"""TaskWorkflow.waiting_since: when the current wait for a person began (the dashboard's waiting times)."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.workflow import engine
from app.workflow.models import Needs, Stage, TaskWorkflow, WorkflowStatus
from tests.factories import make_project


async def _workflow(db, client) -> TaskWorkflow:
    await make_project(client, db, "PAY")
    r = await client.post("/api/projects/PAY/tasks", json={"title": "Refunds"})
    assert r.status_code == 201, r.text
    wf = TaskWorkflow(task_id=uuid.UUID(r.json()["id"]), stage=Stage.design, status=WorkflowStatus.running,
                      started_at=datetime.now(UTC))
    db.add(wf)
    await db.commit()
    return wf


async def test_wait_for_sets_waiting_since_and_leaving_the_wait_clears_it(db, client):
    wf = await _workflow(db, client)
    before = datetime.now(UTC)
    await engine.wait_for(db, wf, Needs.design_approval)
    assert wf.waiting_since is not None and wf.waiting_since >= before
    wf.status = WorkflowStatus.running
    assert wf.waiting_since is None


async def test_a_new_wait_restarts_the_clock(db, client):
    wf = await _workflow(db, client)
    await engine.wait_for(db, wf, Needs.question)
    first = wf.waiting_since
    wf.waiting_since = first - timedelta(hours=1)  # as if the first wait began an hour ago
    await engine.wait_for(db, wf, Needs.escalation)
    assert wf.waiting_since >= first


def test_migration_backfills_waiting_rows_from_updated_at():
    [path] = (Path(__file__).parents[2] / "migrations" / "versions").glob("*_workflow_waiting_since.py")
    source = path.read_text()
    assert "waiting_since = updated_at" in source and "status = 'waiting_human'" in source
