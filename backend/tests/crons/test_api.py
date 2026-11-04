import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.crons.models import Cron, CronRun
from tests.factories import login

BASE = "/api/projects/PAY/crons"


def _body(**over) -> dict:
    body = {"name": "Nightly dependency check", "prompt": "Check the dependencies.", "schedule": "0 2 * * *",
            "timezone": "Africa/Cairo", "agent_id": None, "mode": "tasks"}
    body.update(over)
    return body


async def test_managers_write_members_read(client, db, world):
    await login(client, world.manager)
    r = await client.post(BASE, json=_body())
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    await login(client, world.me)
    assert [c["name"] for c in (await client.get(BASE)).json()] == ["Nightly dependency check"]
    assert (await client.get(f"{BASE}/{cid}")).status_code == 200
    assert (await client.get(f"{BASE}/{cid}/runs")).json() == []
    assert (await client.post(BASE, json=_body())).status_code == 403
    assert (await client.patch(f"{BASE}/{cid}", json={"name": "x"})).status_code == 403
    assert (await client.post(f"{BASE}/{cid}/pause")).status_code == 403
    assert (await client.delete(f"{BASE}/{cid}")).status_code == 403
    await login(client, world.manager)
    assert (await client.delete(f"{BASE}/{cid}")).status_code == 204


async def test_bad_schedule_is_refused(client, db, world):
    await login(client, world.manager)
    r = await client.post(BASE, json=_body(schedule="0 25 * * *"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "schedule_invalid"


async def test_chosen_agent_must_be_usable(client, db, world):
    await login(client, world.manager)
    assert (await client.post(BASE, json=_body(agent_id=str(world.home.id)))).status_code == 422  # not bound
    await login(client, world.other)  # a member can't use the manager's agent, and can't write anyway
    r = await client.post(BASE, json=_body(agent_id=str(world.laptop.id)))
    assert r.status_code == 403
    await login(client, world.manager)
    assert (await client.post(BASE, json=_body(agent_id=str(world.laptop.id)))).status_code == 201


async def test_next_run_at_is_set_and_follows_edits_and_pause(client, db, world):
    await login(client, world.manager)
    cron = (await client.post(BASE, json=_body())).json()
    first = datetime.fromisoformat(cron["next_run_at"])
    assert first > datetime.now(UTC) and first.hour == 0 and first.minute == 0  # 02:00 Cairo = 00:00 UTC
    paused = (await client.post(f"{BASE}/{cron['id']}/pause")).json()
    assert paused["paused"] is True and paused["next_run_at"] is None
    resumed = (await client.post(f"{BASE}/{cron['id']}/resume")).json()
    assert resumed["paused"] is False and datetime.fromisoformat(resumed["next_run_at"]) > datetime.now(UTC)
    edited = (await client.patch(f"{BASE}/{cron['id']}", json={"schedule": "30 16 * * FRI", "timezone": "UTC"})).json()
    nxt = datetime.fromisoformat(edited["next_run_at"])
    assert (nxt.weekday(), nxt.hour, nxt.minute) == (4, 16, 30)
    assert edited["description"] == "At 16:30, only on Friday"


async def test_run_target_is_exactly_one(client, db, world):
    await login(client, world.manager)
    cron = (await client.post(BASE, json=_body())).json()
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "t"})).json()
    async with SessionLocal() as s:
        run = CronRun(id=uuid.uuid4(), cron_id=uuid.UUID(cron["id"]), scheduled_at=datetime.now(UTC), status="queued")
        s.add(run)
        await s.commit()
        run_id = run.id
    base = {"agent_id": world.laptop.id, "policy": "workspace", "prompt": "p"}
    async with SessionLocal() as s:
        s.add(AgentRun(cron_run_id=run_id, task_id=uuid.UUID(task["id"]), **base))
        with pytest.raises(IntegrityError):
            await s.commit()
    async with SessionLocal() as s:
        s.add(AgentRun(cron_run_id=run_id, **base))
        await s.commit()


async def test_one_run_row_per_scheduled_time(client, db, world):
    await login(client, world.manager)
    cron = (await client.post(BASE, json=_body())).json()
    at = datetime(2026, 11, 5, tzinfo=UTC)
    async with SessionLocal() as s:
        s.add(CronRun(cron_id=uuid.UUID(cron["id"]), scheduled_at=at, status="queued"))
        await s.commit()
    async with SessionLocal() as s:
        s.add(CronRun(cron_id=uuid.UUID(cron["id"]), scheduled_at=at, status="queued"))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_list_shows_description_and_last_run(client, db, world):
    await login(client, world.manager)
    cron = (await client.post(BASE, json=_body())).json()
    async with SessionLocal() as s:
        s.add(CronRun(cron_id=uuid.UUID(cron["id"]), scheduled_at=datetime(2026, 11, 4, tzinfo=UTC), status="skipped",
                      skip_reason="no_agent_online"))
        await s.commit()
    [listed] = (await client.get(BASE)).json()
    assert listed["description"] == "At 02:00" and listed["mode"] == "tasks"
    assert listed["last_run"]["status"] == "skipped" and listed["last_run"]["skip_reason"] == "no_agent_online"
    assert (await db.get(Cron, uuid.UUID(cron["id"]))).created_by == world.manager.id
