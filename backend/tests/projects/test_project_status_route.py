"""Changing a project's status: who may, the audit trail, and closing stops the work in it."""

from sqlalchemy import select

from app.agent_runs.service import finish_run
from app.audit.models import AuditLog
from app.core.db import SessionLocal
from app.runner.protocol import runner_message
from tests.factories import login, make_project, make_user
from tests.workflow.test_engine import _runs, _started, _wf


async def test_status_route_reopens_a_closed_project(client, db):
    await make_project(client, db, "PAY")  # signed in as its manager
    r = await client.put("/api/projects/PAY/status", json={"status": "finished"})
    assert r.status_code == 200 and r.json()["status"] == "finished"
    assert (await client.post("/api/projects/PAY/tasks", json={"title": "B"})).status_code == 409
    r = await client.put("/api/projects/PAY/status", json={"status": "active"})
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert (await client.post("/api/projects/PAY/tasks", json={"title": "B"})).status_code == 201
    rows = (await db.execute(
        select(AuditLog).where(AuditLog.action == "project.status_changed").order_by(AuditLog.created_at)
    )).scalars().all()
    assert [r.data for r in rows] == [{"from": "active", "to": "finished"}, {"from": "finished", "to": "active"}]


async def test_setting_the_same_status_changes_nothing(client, db):
    await make_project(client, db, "PAY")
    assert (await client.put("/api/projects/PAY/status", json={"status": "active"})).status_code == 200
    assert (await db.scalar(select(AuditLog.id).where(AuditLog.action == "project.status_changed"))) is None


async def test_only_managers_and_admins_change_status(client, db):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    await login(client, member)
    assert (await client.put("/api/projects/PAY/status", json={"status": "archived"})).status_code == 403
    assert (await client.put("/api/projects/PAY/status", json={"status": "gone"})).status_code == 422


async def test_closing_pauses_workflows_and_cancels_runs(db, tc_factory):
    tc = tc_factory(lifespan=True)
    board, run = await _started(db, tc)
    assert tc.get("/api/projects/PAY/workflows-in-progress").json() == {"count": 1}
    r = tc.put("/api/projects/PAY/status", json={"status": "finished"})
    assert r.status_code == 200, r.text
    assert (await _wf(board.task_id)).status == "paused"
    [cancelled] = await _runs(board.task_id)
    assert cancelled.status == "cancelled"
    assert tc.get("/api/projects/PAY/workflows-in-progress").json() == {"count": 0}
    # the runner's late report for the cancelled run is ignored: nothing reopens
    msg = runner_message.validate_python(
        {"type": "run_finished", "run_id": str(run.id), "outcome": "completed", "summary": ""}
    )
    async with SessionLocal() as s:
        await finish_run(s, board.manager.id, run.id, "completed", "", None, msg)
    assert (await _wf(board.task_id)).status == "paused"
    assert [r.status for r in await _runs(board.task_id)] == ["cancelled"]
    assert tc.put("/api/projects/PAY/status", json={"status": "active"}).status_code == 200
    assert (await _wf(board.task_id)).status == "paused"  # reopening leaves it paused, for a person to resume
