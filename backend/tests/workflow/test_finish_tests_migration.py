"""The data migration that moves tasks stuck on finish_incomplete, although their finish run delivered, to the
finish_tests_failed card (MC-97)."""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.workflow.models import Stage, TaskWorkflow, WorkflowStatus
from tests.workflow.test_engine import _started

DELIVERED = {"outcome": "pr_opened", "pr_url": "https://git.test/o/r/pull/1"}


def _load_migration():
    [path] = (Path(__file__).parents[2] / "migrations" / "versions").glob("*_finish_test_failures.py")
    spec = importlib.util.spec_from_file_location("finish_test_failures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _stuck(tc, started, title, *, stage=Stage.done, reason="finish_incomplete",
                 status=WorkflowStatus.waiting_human, results=(DELIVERED,)) -> uuid.UUID:
    """A task in `stage` escalated with `reason`, with one finish run per entry of `results`, oldest first."""
    r = tc.post("/api/projects/PAY/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    task_id = uuid.UUID(r.json()["id"])
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    async with SessionLocal() as s:
        s.add(TaskWorkflow(task_id=task_id, stage=stage, status=status, escalation_reason=reason,
                           started_at=long_ago))
        for i, result in enumerate(results):
            s.add(AgentRun(
                task_id=task_id, agent_id=started.agent_id, requested_by=started.requested_by,
                policy=started.policy, prompt=started.prompt, status=started.status,
                workflow_role="finish", stage=Stage.done, step_result=result,
                created_at=long_ago + timedelta(minutes=i),
            ))
        await s.commit()
    return task_id


async def _workflows() -> dict[uuid.UUID, TaskWorkflow]:
    async with SessionLocal() as s:
        return {w.task_id: w for w in (await s.scalars(select(TaskWorkflow))).all()}


async def test_stuck_finish_with_a_delivery_moves_to_the_card(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, started = await _started(db, tc)
    waiting = await _stuck(tc, started, "waiting")
    paused = await _stuck(tc, started, "paused", status=WorkflowStatus.paused)
    newest_silent = await _stuck(tc, started, "newest silent", results=(DELIVERED, None))
    review = await _stuck(tc, started, "review", stage=Stage.review, reason="review_incomplete")
    closed = await _stuck(tc, started, "closed", reason="pr_closed")

    async with SessionLocal() as s:
        await s.execute(text(_load_migration().UP_SQL))
        await s.commit()

    wfs = await _workflows()
    for moved in (waiting, paused):
        assert wfs[moved].escalation_reason == "finish_tests_failed"
        assert wfs[moved].finish_tests == {"failures": [], "delivered": True}
    assert wfs[paused].status == WorkflowStatus.paused
    for kept, reason in ((newest_silent, "finish_incomplete"), (review, "review_incomplete"), (closed, "pr_closed")):
        assert wfs[kept].escalation_reason == reason
        assert wfs[kept].finish_tests is None


def test_downgrade_sql_puts_the_reason_back():
    assert "finish_incomplete" in _load_migration().DOWN_SQL
