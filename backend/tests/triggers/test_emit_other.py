"""Escalations, sprints and cron findings write pending firings; triggered chats never fire."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import inspect, select

from app.agent_runs.models import AgentRun, RunStatus
from app.crons import turns
from app.crons.models import Cron, CronRun
from app.mcp_server.auth import current_run
from app.sprints import service as sprints
from app.sprints.models import Sprint
from app.triggers.models import FiringStatus, Trigger, TriggerFiring
from app.workflow import engine
from app.workflow.models import Needs, TaskWorkflow
from tests.chats.helpers import start
from tests.chats.test_chat_workflow import _round
from tests.factories import login
from tests.triggers.helpers import make_trigger
from tests.workflow.test_engine import _runs

ALL_TYPES = {"task_types": ["story", "task", "bug"]}


async def _firings(db, trigger: Trigger) -> list[TriggerFiring]:
    [trigger_id] = inspect(trigger).identity  # no load: the trigger may be expired
    db.expire_all()
    return list((await db.execute(
        select(TriggerFiring).where(TriggerFiring.trigger_id == trigger_id).order_by(TriggerFiring.created_at)
    )).scalars())


async def _sprint(client, name: str = "Sprint 1") -> dict:
    r = await client.post("/api/projects/PAY/sprints", json={
        "name": name, "goal": "ship", "start_date": "2026-11-02", "end_date": "2026-11-06"})
    assert r.status_code == 201, r.text
    return r.json()


async def _cron(db, w, name: str = "Nightly audit") -> Cron:
    cron = Cron(project_id=uuid.UUID(w.project["id"]), name=name, prompt="Look", schedule="0 3 * * *",
                timezone="UTC")
    db.add(cron)
    await db.commit()
    return cron


async def _finish_cron_run(db, cron: Cron, findings: list, *, status: RunStatus = RunStatus.completed) -> None:
    """A cron run that submitted a report with these findings, ended through `turns.on_run_finished`."""
    await db.refresh(cron)  # loaded again, as a fresh session would
    cron_run = CronRun(cron_id=cron.id, scheduled_at=datetime.now(UTC), status="running",
                       report={"summary": "Looked around", "findings": findings, "submitted": True})
    db.add(cron_run)
    await db.flush()
    await turns.on_run_finished(db, AgentRun(cron_run_id=cron_run.id, status=status))
    await db.commit()


async def test_an_escalation_fires_needs_person(client, db, world):
    await login(client, world.manager)
    needs = await make_trigger(db, world, "task_needs_person", ALL_TYPES)
    r = await client.post("/api/projects/PAY/tasks", json={"title": "Flaky build", "type": "bug"})
    assert r.status_code == 201, r.text
    wf = TaskWorkflow(task_id=uuid.UUID(r.json()["id"]))
    db.add(wf)
    await db.commit()
    await db.refresh(wf)

    await engine.wait_for(db, wf, Needs.question)  # a question is no escalation
    await db.commit()
    assert await _firings(db, needs) == []

    await db.refresh(wf)
    await engine.escalate(db, wf, "retries_exhausted")
    await db.commit()
    [firing] = await _firings(db, needs)
    assert firing.status == FiringStatus.pending and firing.event == "task_needs_person"
    assert firing.subject["label"] == r.json()["key"]
    assert firing.subject["note"] == "needs a person: retries exhausted"
    assert "Event: escalated: retries exhausted by the workflow" in firing.what


async def test_starting_and_completing_a_sprint_fire(client, db, world):
    await login(client, world.manager)
    started = await make_trigger(db, world, "sprint_started")
    completed = await make_trigger(db, world, "sprint_completed")
    sprint = await _sprint(client)

    assert (await client.post(f"/api/sprints/{sprint['id']}/start")).status_code == 200
    [firing] = await _firings(db, started)
    assert firing.subject["kind"] == "sprint" and firing.subject["label"] == "Sprint 1"
    assert firing.subject["note"] == "started"
    assert await _firings(db, completed) == []

    r = await client.post(f"/api/sprints/{sprint['id']}/complete", json={"move_open_to": "backlog"})
    assert r.status_code == 200, r.text
    [firing] = await _firings(db, completed)
    assert firing.subject["note"] == "completed"
    assert len(await _firings(db, started)) == 1


async def test_sprints_started_by_a_triggered_chat_fire_nothing(client, db, world):
    started = await make_trigger(db, world, "sprint_started")
    completed = await make_trigger(db, world, "sprint_completed")
    triggered = await start(client, mode="freestyle")  # as the laptop agent's owner
    db.add(TriggerFiring(trigger_id=started.id, event="sprint_started", subject={}, what="",
                         status=FiringStatus.started, chat_id=uuid.UUID(triggered["id"])))
    await db.commit()
    await login(client, world.manager)
    sprint_id = uuid.UUID((await _sprint(client))["id"])

    [run] = await _runs((await _round(db, triggered)).id)
    token = current_run.set(run)
    try:
        sprint = await db.get(Sprint, sprint_id)
        await sprints.start(db, sprint)
        await db.commit()
        await sprints.complete(db, sprint, "backlog")
        await db.commit()
    finally:
        current_run.reset(token)
    assert [f.chat_id for f in await _firings(db, started)] == [uuid.UUID(triggered["id"])]
    assert await _firings(db, completed) == []


async def test_a_cron_run_with_findings_fires_and_one_without_does_not(db, world):
    cron = await _cron(db, world)
    found = await make_trigger(db, world, "cron_found")

    await _finish_cron_run(db, cron, [])
    await _finish_cron_run(db, cron, [{"title": "Lost run", "detail": "the agent failed"}],
                           status=RunStatus.failed)
    assert await _firings(db, found) == []

    await _finish_cron_run(db, cron, [{"title": "Stale dependency", "detail": "requests is 3 majors behind"}])
    [firing] = await _firings(db, found)
    assert firing.event == "cron_found" and firing.subject["kind"] == "cron_run"
    assert firing.subject["label"] == "Nightly audit" and firing.subject["note"] == "1 finding"
    assert "- Stale dependency: requests is 3 majors behind" in firing.what


async def test_cron_found_for_one_cron_ignores_others(db, world):
    nightly = await _cron(db, world)
    weekly = await _cron(db, world, "Weekly review")
    only_weekly = await make_trigger(db, world, "cron_found", {"cron_id": str(weekly.id)})

    await _finish_cron_run(db, nightly, [{"title": "One", "detail": "a"}])
    assert await _firings(db, only_weekly) == []
    await _finish_cron_run(db, weekly, [{"title": "Two", "detail": "b"}])
    [firing] = await _firings(db, only_weekly)
    assert firing.subject["label"] == "Weekly review"
