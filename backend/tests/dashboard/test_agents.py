"""Agents, running and queued runs, failed runs."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.agents.models import Agent, AgentBinding
from app.runner.registry import RunnerRegistry, registry
from app.workflow.models import WorkflowDocument
from tests.dashboard.conftest import add_question, add_run, add_task, add_workflow, dash, task_key
from tests.factories import login


async def test_agents_are_ordered_working_idle_offline(client, db, world, monkeypatch):
    idle = Agent(owner_id=world.pay_manager.id, name="Alpha", program="codex")
    off = Agent(owner_id=world.pay_manager.id, name="Aardvark", program="codex")
    db.add_all([idle, off])
    await db.flush()
    db.add_all([AgentBinding(agent_id=a.id, project_id=world.pay.id, local_path="/w") for a in (idle, off)])
    await db.commit()
    task = await add_task(db, world.pay)
    await add_run(db, world.agent, task=task, status="running", started_at=datetime.now(UTC))
    monkeypatch.setattr(registry, "available_agents",
                        lambda owner: {idle.id} if owner == world.pay_manager.id else set())
    await login(client, world.viewer)
    body = await dash(client)
    assert [(a["name"], a["status"], a["runs_today"]) for a in body["agents"]] == [
        ("Viewer bot", "busy", 1), ("Alpha", "online", 0), ("Aardvark", "offline", 0)]
    assert (body["numbers"]["agents_working"], body["numbers"]["agents_online"]) == (1, 2)
    assert [a["name"] for a in (await dash(client, "mine"))["agents"]] == ["Viewer bot"]


async def test_running_rows_show_build_progress_and_answering_runs(client, db, world):
    task = await add_task(db, world.pay)
    await add_workflow(db, task, stage="build", status="running", agent=world.agent)
    db.add(WorkflowDocument(task_id=task.id, kind="plan", version=1, body_md="", status="approved",
                            steps=[{"title": "a"}, {"title": "b"}, {"title": "c"}]))
    await db.commit()
    await add_run(db, world.agent, task=task, stage="build", step=2,
                  started_at=datetime.now(UTC) - timedelta(minutes=5))
    asking = await add_task(db, world.web)
    q = await add_question(db, world.pay, status="routed", from_task=asking)
    await add_run(db, world.agent, question=q, started_at=datetime.now(UTC))
    await add_run(db, world.other_agent, task=await add_task(db, world.web))  # WEB: not shown
    await login(client, world.viewer)
    rows = (await dash(client))["running"]
    assert [(r["task_key"], r["question_from"]) for r in rows] == [(None, "WEB"), (task_key(task), None)]
    build = rows[1]
    assert (build["agent_name"], build["stage"], build["step"], build["steps_total"]) == ("Viewer bot", "build", 2, 3)
    assert build["link"] == f"/projects/PAY/board?task={task_key(task)}"
    assert rows[0]["link"] == f"/questions/{q.id}"


async def test_queued_lists_five_and_counts_all(client, db, world):
    for _ in range(7):
        await add_run(db, world.agent, task=await add_task(db, world.pay), status="queued", stage="plan")
    await add_run(db, world.other_agent, task=await add_task(db, world.web), status="queued")
    await login(client, world.viewer)
    body = await dash(client)
    assert body["queued"]["total"] == 7 and len(body["queued"]["items"]) == 5
    assert body["queued"]["items"][0] == {"task_key": "PAY-1", "stage": "plan"}
    assert body["numbers"]["runs_queued"] == 7


async def test_failed_runs_and_success_rate_over_24_hours(client, db, world):
    now = datetime.now(UTC)
    for status, ago in [("completed", 1), ("completed", 2), ("completed", 3), ("failed", 4), ("failed", 48),
                        ("cancelled", 5)]:
        await add_run(db, world.agent, task=await add_task(db, world.pay), status=status,
                      started_at=now - timedelta(hours=ago + 1), finished_at=now - timedelta(hours=ago))
    await add_run(db, world.other_agent, task=await add_task(db, world.web), status="failed", finished_at=now)
    await login(client, world.viewer)
    n = (await dash(client))["numbers"]
    assert (n["failed_24h"], n["success_rate_24h"]) == (1, 0.75)


def test_connected_count_skips_closed_connections():
    reg = RunnerRegistry()
    open_, closed = SimpleNamespace(closed=asyncio.Event()), SimpleNamespace(closed=asyncio.Event())
    closed.closed.set()
    reg._conns = {uuid.uuid4(): open_, uuid.uuid4(): closed}
    assert reg.connected_count() == 1
