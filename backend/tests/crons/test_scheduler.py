"""The scheduler: each scheduled time runs once, on one agent, or is skipped with a reason."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.agent_runs.service import finish_run
from app.agents.models import AgentBinding
from app.core.db import SessionLocal
from app.crons import scheduler
from app.crons.models import Cron, CronRun
from app.notifications.models import Notification
from app.runner.protocol import GitState, RunFinished
from app.runner.registry import CRONS_CAPABILITY, SECRETS_CAPABILITY, registry
from tests.agent_runs.test_dispatch import _fake_conn, _FakeSocket
from tests.factories import login

BASE = "/api/projects/PAY/crons"
HEAD_A, HEAD_B = "a" * 40, "b" * 40


async def _cron(client, world, **over) -> uuid.UUID:
    await login(client, world.manager)
    body = {"name": "Nightly check", "prompt": "Check the dependencies.", "schedule": "0 2 * * *", "timezone": "UTC",
            "agent_id": None, "mode": "report"}
    body.update(over)
    r = await client.post(BASE, json=body)
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


async def _due(cron_id: uuid.UUID, at: datetime) -> None:
    async with SessionLocal() as s:
        await s.execute(update(Cron).where(Cron.id == cron_id).values(next_run_at=at))
        await s.commit()


async def _rows(model, *where) -> list:
    async with SessionLocal() as s:
        return list((await s.execute(select(model).where(*where))).scalars())


async def _online(user, agent, *caps):
    sock = _FakeSocket()
    conn = await _fake_conn(user, {"id": str(agent.id)}, sock)
    conn.capabilities.update(caps)
    return sock


async def test_one_run_per_scheduled_time_even_with_two_ticks(client, db, world):
    cron_id = await _cron(client, world)
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await asyncio.gather(scheduler.tick(now), scheduler.tick(now))
    assert len(await _rows(CronRun, CronRun.cron_id == cron_id)) == 1
    assert len(await _rows(AgentRun, AgentRun.cron_run_id.is_not(None))) == 1
    [cron] = await _rows(Cron, Cron.id == cron_id)
    assert cron.next_run_at > now


async def test_previous_run_still_going_skips(client, db, world):
    cron_id = await _cron(client, world)
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=2))
    await scheduler.tick(now)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    runs = sorted(await _rows(CronRun, CronRun.cron_id == cron_id), key=lambda r: r.scheduled_at)
    assert [(r.status, r.skip_reason) for r in runs] == [("queued", None), ("skipped", "previous_running")]


async def test_missed_by_more_than_an_hour_records_one_skip_and_no_run(client, db, world):
    cron_id = await _cron(client, world)
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(hours=3))
    await scheduler.tick(now)
    [run] = await _rows(CronRun, CronRun.cron_id == cron_id)
    assert (run.status, run.skip_reason) == ("skipped", "missed")
    assert await _rows(AgentRun, AgentRun.cron_run_id.is_not(None)) == []


async def test_queued_for_15_minutes_is_skipped_no_agent_online(client, db, world):
    cron_id = await _cron(client, world)
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    await scheduler.tick(now + timedelta(minutes=16))
    [run] = await _rows(CronRun, CronRun.cron_id == cron_id)
    assert (run.status, run.skip_reason) == ("skipped", "no_agent_online")
    [agent_run] = await _rows(AgentRun, AgentRun.cron_run_id == run.id)
    assert agent_run.status == RunStatus.cancelled


async def test_running_over_30_minutes_is_cancelled_and_marked_timed_out(client, db, world):
    cron_id = await _cron(client, world)
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.cron_run_id.is_not(None))
                        .values(status=RunStatus.running, started_at=now - timedelta(minutes=31)))
        await s.commit()
    await scheduler.tick(now)
    [run] = await _rows(CronRun, CronRun.cron_id == cron_id)
    assert (run.status, run.skip_reason) == ("failed", "timed_out")


async def test_chosen_agent_gone_skips_no_agent_and_tells_managers(client, db, world):
    manager_id, laptop_id = world.manager.id, world.laptop.id
    cron_id = await _cron(client, world, agent_id=str(laptop_id))
    async with SessionLocal() as s:
        await s.execute(delete(AgentBinding).where(AgentBinding.agent_id == laptop_id))
        await s.commit()
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    [run] = await _rows(CronRun, CronRun.cron_id == cron_id)
    assert (run.status, run.skip_reason) == ("skipped", "no_agent")
    assert await _rows(AgentRun, AgentRun.cron_run_id.is_not(None)) == []
    notes = await _rows(Notification, Notification.user_id == manager_id)
    assert any("Nightly check" in n.title for n in notes)


async def test_any_free_agent_prefers_online_and_needs_crons_capability(client, db, world):
    manager, mgr_bot_id = world.manager, world.mgr_bot.id
    cron_id = await _cron(client, world)
    sock = await _online(manager, world.mgr_bot, CRONS_CAPABILITY)
    try:
        now = datetime.now(UTC)
        await _due(cron_id, now - timedelta(minutes=1))
        await scheduler.tick(now)
    finally:
        registry._conns.pop(manager.id, None)
    [agent_run] = await _rows(AgentRun, AgentRun.cron_run_id.is_not(None))
    assert agent_run.agent_id == mgr_bot_id
    assert [m for m in map(json.loads, sock.sent) if m["type"] == "run_start"]


async def test_run_start_carries_cron_branch_and_workspace_policy(client, db, world):
    manager = world.manager
    cron_id = await _cron(client, world, agent_id=str(world.mgr_bot.id))
    await client.post("/api/projects/PAY/secrets", json={"name": "API_KEY", "description": "x", "value": "key-12345"})
    sock = await _online(manager, world.mgr_bot, CRONS_CAPABILITY, SECRETS_CAPABILITY)
    try:
        now = datetime.now(UTC)
        await _due(cron_id, now - timedelta(minutes=1))
        await scheduler.tick(now)
    finally:
        registry._conns.pop(manager.id, None)
    [start] = [m for m in map(json.loads, sock.sent) if m["type"] == "run_start"]
    assert start["cron"] == {"id": str(cron_id), "branch": "main"} and start["policy"] == "workspace"
    assert start["task"]["key"] == f"CRN-{cron_id.hex[:12]}" and start["role"] == "cron"
    assert start["secrets"] == [{"name": "API_KEY", "value": "key-12345"}]
    assert "Check the dependencies." in start["prompt"]
    from app.workflow.context import DOCS_NOTE

    assert DOCS_NOTE in start["prompt"]
    [run] = await _rows(CronRun, CronRun.cron_id == cron_id)
    assert run.status == "running"


async def test_a_commit_fails_the_run(client, db, world):
    manager_id = world.manager.id
    cron_id = await _cron(client, world, agent_id=str(world.mgr_bot.id))
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.cron_run_id.is_not(None)).values(status=RunStatus.running))
        await s.commit()
    [agent_run] = await _rows(AgentRun, AgentRun.cron_run_id.is_not(None))
    async with SessionLocal() as s:
        await finish_run(s, manager_id, agent_run.id, "completed", "", None, RunFinished(
            type="run_finished", run_id=agent_run.id, outcome="completed", summary="",
            git_before=GitState(head=HEAD_A, dirty=False), git_after=GitState(head=HEAD_B, dirty=False)))
    [run] = await _rows(CronRun, CronRun.cron_id == cron_id)
    assert (run.status, run.skip_reason, run.commit) == ("failed", "made_a_commit", HEAD_A)


async def test_run_now_starts_one_and_respects_a_running_one(client, db, world):
    cron_id = await _cron(client, world)
    first = await client.post(f"{BASE}/{cron_id}/run-now")
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "queued"
    second = (await client.post(f"{BASE}/{cron_id}/run-now")).json()
    assert (second["status"], second["skip_reason"]) == ("skipped", "previous_running")
    await login(client, world.me)
    assert (await client.post(f"{BASE}/{cron_id}/run-now")).status_code == 403
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.cron_run_id.is_not(None))) == 1


async def test_methodology_has_cron_in_the_crons_group(client, db, world):
    listed = {m["key"]: m for m in (await client.get("/api/methodology")).json()}
    assert listed["cron"]["stage"] == "crons"


async def test_the_dashboard_has_no_broken_link_for_a_cron_run(client, db, world):
    cron_id = await _cron(client, world, agent_id=None)
    now = datetime.now(UTC)
    await _due(cron_id, now - timedelta(minutes=1))
    await scheduler.tick(now)
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.cron_run_id.is_not(None)).values(status=RunStatus.running))
        await s.commit()
    from app.auth.models import Role
    from tests.factories import make_user

    await login(client, await make_user(db, role=Role.admin))  # an admin's dashboard has every project's runs
    body = (await client.get("/api/dashboard", params={"scope": "teams"})).json()
    assert all(r["link"] != "/questions/None" for r in body["running"]), body["running"]
