"""The data migration that moves rounds already stuck on a human review (after an agent merged) to the quiet wait."""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text

from app.core.crypto import encrypt
from app.git.models import GitConnection, TaskPullRequest
from app.tasks.models import TaskEvent
from app.workflow.models import Needs, Stage, TaskWorkflow, WorkflowStatus
from tests.factories import make_project


def _load_migration():
    [path] = (Path(__file__).parents[2] / "migrations" / "versions").glob("*_merge_confirmation_waits.py")
    spec = importlib.util.spec_from_file_location("merge_confirmation_waits", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _stuck_round(db, client, conn, title, *, mode="agent", merged=True, escalated=False, back_merge=False):
    r = await client.post("/api/projects/PAY/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    task_id = uuid.UUID(r.json()["id"])
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    db.add(TaskWorkflow(
        task_id=task_id, stage=Stage.done, status=WorkflowStatus.waiting_human, needs=Needs.human_code_review,
        finish_pr_review=mode, waiting_since=long_ago, started_at=long_ago,
        back_merge_pr_url="https://git.test/o/r/pull/2" if back_merge else None,
    ))
    db.add(TaskPullRequest(
        task_id=task_id, url="https://git.test/o/r/pull/1", connection_id=conn.id, failures=4,
        next_check_at=datetime.now(UTC) + timedelta(days=1),
    ))
    await db.flush()
    db.add(TaskEvent(task_id=task_id, kind="pr.agent_reviewed", data={"merged": merged},
                     created_at=long_ago + timedelta(minutes=1)))
    if escalated:
        db.add(TaskEvent(task_id=task_id, kind="workflow.escalated", data={},
                         created_at=long_ago + timedelta(minutes=2)))
    return task_id


async def test_only_agent_merged_rounds_without_a_later_escalation_move(db, client):
    await make_project(client, db, "PAY")
    conn = GitConnection(name="GitHub", kind="github", base_url="https://git.test", token_enc=encrypt("t"))
    db.add(conn)
    await db.flush()
    qualifying = await _stuck_round(db, client, conn, "qualifying")
    human = await _stuck_round(db, client, conn, "human", mode="human")
    escalated = await _stuck_round(db, client, conn, "escalated", escalated=True)
    back_merge = await _stuck_round(db, client, conn, "back merge", back_merge=True)
    not_merged = await _stuck_round(db, client, conn, "not merged", merged=False)
    await db.commit()

    before = datetime.now(UTC)
    await db.execute(text(_load_migration().MOVE_SQL))
    await db.commit()
    db.expire_all()

    needs = {w.task_id: w for w in (await db.scalars(select(TaskWorkflow))).all()}
    assert needs[qualifying].needs == Needs.merge_confirmation
    assert needs[qualifying].waiting_since >= before
    for other in (human, escalated, back_merge, not_merged):
        assert needs[other].needs == Needs.human_code_review
        assert needs[other].waiting_since < before
    prs = {p.task_id: p for p in (await db.scalars(select(TaskPullRequest))).all()}
    assert prs[qualifying].failures == 0 and prs[qualifying].next_check_at >= before
    assert prs[human].failures == 4


def test_downgrade_sql_puts_the_wait_back():
    assert "human_code_review" in _load_migration().DOWN_SQL
