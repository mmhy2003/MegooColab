"""Try it: a manager fires a trigger once now on the newest thing that matches; members read its firings."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.audit.models import AuditLog
from app.chats.models import Chat
from app.core.db import SessionLocal
from app.tasks.models import Task
from app.triggers import fire
from app.triggers.models import FiringStatus, TriggerFiring
from tests.factories import login
from tests.triggers.helpers import make_trigger
from tests.workflow.test_engine import _runs

BASE = "/api/projects/PAY/triggers"
ALL_TYPES = {"task_types": ["story", "task", "bug"]}
SUBJECT = {"kind": "task", "label": "PAY-3", "title": "Fix the login", "link": "/projects/PAY/tasks/3", "note": ""}


async def _task(client, title: str) -> dict:
    r = await client.post("/api/projects/PAY/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


async def _firings(trigger_id: uuid.UUID) -> list[TriggerFiring]:
    async with SessionLocal() as s:
        return list((await s.execute(
            select(TriggerFiring).where(TriggerFiring.trigger_id == trigger_id).order_by(TriggerFiring.created_at)
        )).scalars())


async def test_try_fires_on_the_newest_match_now(client, db, world):
    await login(client, world.manager)
    await _task(client, "Older one")
    newest = await _task(client, "Newest one")
    trigger = await make_trigger(db, world, "task_created", ALL_TYPES, name="Triage", prompt="Triage it.",
                                 any_agent=False, agent_id=world.mgr_bot.id)

    r = await client.post(f"{BASE}/{trigger.id}/try")

    assert r.status_code == 201, r.text
    out = r.json()
    assert out["subject"]["label"] == newest["key"] and out["agent"]["id"] == str(world.mgr_bot.id)
    assert out["chat_id"] is not None and out["result"] in ("waiting_agent", "working")
    [firing] = await _firings(trigger.id)
    assert firing.tried is True and firing.status == FiringStatus.started and firing.event == "task_created"
    assert newest["key"] in firing.what
    async with SessionLocal() as s:
        chat = await s.get(Chat, firing.chat_id)
        task_id = await s.scalar(select(Task.id).where(Task.chat_id == chat.id))
        audit = (await s.execute(select(AuditLog).where(AuditLog.action == "trigger.tried",
                                                        AuditLog.target_id == trigger.id))).scalars().all()
    assert chat.title == f"Triage · {newest['key']}" and chat.started_by == world.manager.id
    assert [r.workflow_role for r in await _runs(task_id)] == ["freestyle"]
    assert [a.actor_user_id for a in audit] == [world.manager.id]


async def test_try_on_a_paused_trigger_works(client, db, world):
    await login(client, world.manager)
    await _task(client, "Something")
    trigger = await make_trigger(db, world, "task_created", ALL_TYPES, paused=True)

    r = await client.post(f"{BASE}/{trigger.id}/try")

    assert r.status_code == 201, r.text
    [firing] = await _firings(trigger.id)
    assert firing.status == FiringStatus.started and firing.chat_id is not None


async def test_try_counts_toward_the_hourly_limit(client, db, world):
    await login(client, world.manager)
    await _task(client, "Something")
    trigger = await make_trigger(db, world, "task_created", ALL_TYPES)
    now = datetime.now(UTC)
    for _ in range(fire.HOURLY_LIMIT - 1):
        db.add(TriggerFiring(trigger_id=trigger.id, event=trigger.event, subject=SUBJECT, what="x",
                             status=FiringStatus.started, started_at=now))
    await db.commit()

    first = await client.post(f"{BASE}/{trigger.id}/try")
    second = await client.post(f"{BASE}/{trigger.id}/try")

    assert first.status_code == second.status_code == 201
    assert first.json()["result"] != "skipped"
    assert (second.json()["result"], second.json()["excerpt"]) == ("skipped", "rate_limited")
    tried = [f for f in await _firings(trigger.id) if f.tried]
    assert [f.status for f in tried] == [FiringStatus.started, FiringStatus.skipped]


async def test_nothing_to_try_and_pr_merged_are_refused(client, db, world):
    await login(client, world.manager)
    nothing = await make_trigger(db, world, "task_created", {"task_types": ["bug"]})  # PAY has no bug
    merged = await make_trigger(db, world, "pr_merged")

    for trigger in (nothing, merged):
        r = await client.post(f"{BASE}/{trigger.id}/try")
        assert (r.status_code, r.json()["detail"]) == (422, "nothing_to_try"), r.text
        assert await _firings(trigger.id) == []


async def test_firings_newest_first_with_limit(client, db, world):
    trigger = await make_trigger(db, world, "task_finished")
    base = datetime.now(UTC) - timedelta(minutes=10)
    ids = []
    for i in range(3):
        firing = TriggerFiring(trigger_id=trigger.id, event=trigger.event, subject=SUBJECT | {"label": f"PAY-{i}"},
                               what="x", status=FiringStatus.skipped, skip_reason="no_agent",
                               created_at=base + timedelta(minutes=i))
        db.add(firing)
        await db.flush()
        ids.append(str(firing.id))
    await db.commit()

    await login(client, world.me)  # members read the history
    r = await client.get(f"{BASE}/{trigger.id}/firings")
    assert r.status_code == 200, r.text
    assert [f["id"] for f in r.json()] == ids[::-1]
    assert r.json()[0]["result"] == "skipped" and r.json()[0]["subject"]["label"] == "PAY-2"

    r = await client.get(f"{BASE}/{trigger.id}/firings", params={"limit": 2})
    assert [f["id"] for f in r.json()] == ids[:0:-1]
    for bad in (0, 201):
        assert (await client.get(f"{BASE}/{trigger.id}/firings", params={"limit": bad})).status_code == 422
    assert (await client.get(f"{BASE}/{uuid.uuid4()}/firings")).status_code == 404


async def test_members_cannot_try(client, db, world):
    await login(client, world.manager)
    await _task(client, "Something")
    trigger = await make_trigger(db, world, "task_created", ALL_TYPES)

    await login(client, world.me)
    assert (await client.post(f"{BASE}/{trigger.id}/try")).status_code == 403
    assert await _firings(trigger.id) == []
