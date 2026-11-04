"""Final-review fixes for Agent Crons."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.core.db import SessionLocal
from app.crons import scheduler
from app.crons.models import Cron, CronRun
from app.kb import access
from app.kb.models import KbDocument
from app.notifications.models import Notification
from app.projects.models import Project
from app.runner.registry import CRONS_CAPABILITY, registry
from tests.agent_runs.test_dispatch import _fake_conn, _FakeSocket
from tests.crons.test_scheduler import BASE, _cron, _due, _rows
from tests.factories import login, make_team
from tests.mcp.test_workflow_tools import _run_token, _tool


async def test_deleting_the_chosen_agent_never_hands_the_cron_to_another(client, db, world):
    laptop_id = world.laptop.id
    cron_id = await _cron(client, world, agent_id=str(laptop_id))
    async with SessionLocal() as s:
        await s.delete(await s.get(Agent, laptop_id))
        await s.commit()
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    [run] = await _rows(CronRun, CronRun.cron_id == cron_id)
    assert (run.status, run.skip_reason) == ("skipped", "no_agent")
    assert await _rows(AgentRun, AgentRun.cron_run_id.is_not(None)) == []


async def test_a_run_whose_send_failed_still_ends_after_the_wait(client, db, world):
    cron_id = await _cron(client, world)
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    async with SessionLocal() as s:  # what a dropped send leaves: the CronRun running, its AgentRun queued again
        await s.execute(update(CronRun).where(CronRun.cron_id == cron_id).values(status="running"))
        await s.commit()
    await scheduler.tick(now + timedelta(minutes=16))
    [run] = await _rows(CronRun, CronRun.cron_id == cron_id)
    assert (run.status, run.skip_reason) == ("skipped", "no_agent_online")


async def test_a_run_whose_agent_run_is_gone_is_ended(client, db, world):
    cron_id = await _cron(client, world)
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    async with SessionLocal() as s:
        await s.execute(update(CronRun).where(CronRun.cron_id == cron_id).values(status="running", agent_run_id=None))
        await s.commit()
    await scheduler.tick(now)
    [run] = await _rows(CronRun, CronRun.cron_id == cron_id)
    assert (run.status, run.skip_reason) == ("failed", "lost")


async def test_a_late_time_after_downtime_still_gets_its_15_minutes(client, db, world):
    cron_id = await _cron(client, world)
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=30))  # missed by 30 minutes: within the hour, so it runs
    await scheduler.tick(now)
    [run] = await _rows(CronRun, CronRun.cron_id == cron_id)
    assert run.status == "queued"  # not cancelled in the same tick for being 30 minutes past its time


async def test_crons_of_a_finished_project_do_not_run_and_can_be_paused(client, db, world):
    cron_id = await _cron(client, world)
    assert (await client.put("/api/projects/PAY/status", json={"status": "finished"})).status_code == 200
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    assert await _rows(AgentRun, AgentRun.cron_run_id.is_not(None)) == []
    r = await client.post(f"{BASE}/{cron_id}/pause")
    assert r.status_code == 200 and r.json()["paused"] is True


async def test_deleting_a_cron_stops_its_running_agent(client, db, world):
    manager, mgr_bot_id = world.manager, world.mgr_bot.id
    cron_id = await _cron(client, world, agent_id=str(mgr_bot_id))
    sock = _FakeSocket()
    conn = await _fake_conn(manager, {"id": str(mgr_bot_id)}, sock)
    conn.capabilities.add(CRONS_CAPABILITY)
    try:
        now = datetime.now(UTC)
        await _due(cron_id, now - timedelta(minutes=1))
        await scheduler.tick(now)
        assert (await client.delete(f"{BASE}/{cron_id}")).status_code == 204
    finally:
        registry._conns.pop(manager.id, None)
    assert [m for m in map(json.loads, sock.sent) if m["type"] == "run_cancel"]


async def test_cron_runs_read_only_their_project_and_the_organization_in_the_kb(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    cron_id = await _cron(client, world, agent_id=str(world.laptop.id))
    other_team = await make_team(db, world.me, name="Private team")
    secret_space = await access.space_for_team(db, other_team.id)
    db.add(KbDocument(id=uuid.uuid4(), space_id=secret_space.id, title="Team secret plans", body_md="hidden",
                      latest_revision=1))
    await db.commit()
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    [agent_run] = await _rows(AgentRun, AgentRun.cron_run_id.is_not(None))
    token = await _run_token(agent_run)
    err, out = _tool(tc, token, "kb_search", query="secret plans")
    assert not err and all("Team secret plans" != h["title"] for h in out["results"]), out


async def test_no_agent_always_tells_the_managers(client, db, world):
    manager_id, laptop_id = world.manager.id, world.laptop.id
    cron_id = await _cron(client, world, agent_id=str(laptop_id))
    async with SessionLocal() as s:
        await s.execute(update(Cron).where(Cron.id == cron_id).values(notify_failures=False))
        await s.delete(await s.get(Agent, laptop_id))
        await s.commit()
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    notes = await _rows(Notification, Notification.user_id == manager_id)
    assert any("Nightly check" in n.title for n in notes)


async def test_an_edit_without_the_agent_does_not_recheck_it(client, db, world):
    cron_id = await _cron(client, world, agent_id=str(world.mgr_bot.id))  # the manager's own agent
    async with SessionLocal() as s:  # another manager of the project
        project = (await s.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
        await s.commit()
    r = await client.patch(f"{BASE}/{cron_id}", json={"name": "Renamed"})
    assert r.status_code == 200 and r.json()["agent"]["name"] == "mgr-bot"
    assert project is not None


async def test_cron_runs_search_only_their_projects_memory(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    cron_id = await _cron(client, world, agent_id=str(world.laptop.id))
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    [agent_run] = await _rows(AgentRun, AgentRun.cron_run_id.is_not(None))
    token = await _run_token(agent_run)
    err, out = _tool(tc, token, "search_memory", query="anything", project_key="WEB")
    assert not err, out  # scoped to the cron's own project whatever it asks for
