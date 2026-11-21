"""The trigger loop: each pending firing starts a freestyle chat as the trigger's owner, or is skipped with a reason."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.auth.models import User, UserStatus
from app.chats.models import Chat, ChatMode
from app.core.db import SessionLocal
from app.notifications.models import Kind, Notification
from app.projects.models import Project, ProjectStatus
from app.tasks.models import Task
from app.triggers import fire
from app.triggers.models import FiringStatus, TriggerFiring
from tests.factories import make_user
from tests.triggers.helpers import make_trigger
from tests.workflow.test_engine import _runs

SUBJECT = {"kind": "task", "label": "PAY-3", "title": "Fix the login", "link": "/tasks/PAY-3", "note": ""}


async def _pending(db, trigger, *, tried: bool = False) -> uuid.UUID:
    firing = TriggerFiring(trigger_id=trigger.id, event=trigger.event, subject=SUBJECT, what="PAY-3 finished.",
                           tried=tried)
    db.add(firing)
    await db.commit()
    return firing.id


async def _firing(firing_id: uuid.UUID) -> TriggerFiring | None:
    async with SessionLocal() as s:
        return await s.get(TriggerFiring, firing_id)


async def _skipped(trigger_id: uuid.UUID) -> list[Notification]:
    async with SessionLocal() as s:
        rows = await s.execute(select(Notification).where(Notification.title.like("Trigger % skipped"),
                                                          Notification.link.like(f"%/triggers/{trigger_id}")))
        return list(rows.scalars())


async def test_a_firing_starts_a_freestyle_chat(client, db, world):
    trigger = await make_trigger(db, world, "task_finished", name="Release notes", prompt="Write the notes.",
                                 keep_open=True)
    firing_id = await _pending(db, trigger)

    await fire.tick()

    firing = await _firing(firing_id)
    assert firing.status == FiringStatus.started and firing.skip_reason is None
    assert firing.started_at is not None and firing.keep_open is True
    async with SessionLocal() as s:
        chat = await s.get(Chat, firing.chat_id)
        [task] = (await s.execute(select(Task).where(Task.chat_id == chat.id))).scalars().all()
    assert chat.title == "Release notes · PAY-3" and chat.mode == ChatMode.freestyle
    assert chat.started_by == world.manager.id and chat.agent_id == firing.agent_id
    assert task.description_md == "Write the notes."
    runs = await _runs(task.id)
    assert [(r.workflow_role, r.status) for r in runs] == [("freestyle", "queued")]


async def test_the_chosen_agent_or_any_usable_one(client, db, world):
    chosen = await make_trigger(db, world, "task_finished", any_agent=False, agent_id=world.mgr_bot.id)
    anyone = await make_trigger(db, world, "task_finished", any_agent=True)
    unbound = await make_trigger(db, world, "task_finished", any_agent=False, agent_id=world.home.id)
    not_mine = await make_trigger(db, world, "task_finished", any_agent=False, agent_id=world.mgr_bot.id,
                                  owner_id=world.me.id)
    ids = [await _pending(db, t) for t in (chosen, anyone, unbound, not_mine)]

    await fire.tick()

    chosen_f, anyone_f, unbound_f, not_mine_f = [await _firing(i) for i in ids]
    assert (chosen_f.status, chosen_f.agent_id) == (FiringStatus.started, world.mgr_bot.id)
    # any usable agent: neither is online nor busy, so the first by name
    assert (anyone_f.status, anyone_f.agent_id) == (FiringStatus.started, world.laptop.id)
    assert (unbound_f.status, unbound_f.skip_reason, unbound_f.chat_id) == (FiringStatus.skipped, "no_agent", None)
    # a member may not use the manager's agent
    assert (not_mine_f.status, not_mine_f.skip_reason) == (FiringStatus.skipped, "no_agent")


async def test_skip_reasons(client, db, world):
    paused = await make_trigger(db, world, "task_finished", paused=True)
    paused_id = await _pending(db, paused)
    tried_id = await _pending(db, paused, tried=True)
    no_owner = await make_trigger(db, world, "task_finished", owner_id=None)
    no_owner_id = await _pending(db, no_owner)
    gone_user = await make_user(db, name="Gone Gina")
    gone = await make_trigger(db, world, "task_finished", owner_id=gone_user.id)
    await db.execute(update(User).where(User.id == gone_user.id).values(status=UserStatus.deactivated))
    await db.commit()
    gone_id = await _pending(db, gone)
    outsider = await make_user(db, name="Otis Outsider")  # in no team of PAY
    no_access = await make_trigger(db, world, "task_finished", owner_id=outsider.id)
    no_access_id = await _pending(db, no_access)
    no_agent = await make_trigger(db, world, "task_finished", any_agent=False, agent_id=None)
    no_agent_id = await _pending(db, no_agent)

    await fire.tick()

    assert ((await _firing(paused_id)).status, (await _firing(paused_id)).skip_reason) == ("skipped", "paused")
    assert (await _firing(tried_id)).status == FiringStatus.started
    for firing_id, reason in ((no_owner_id, "owner_gone"), (gone_id, "owner_gone"), (no_access_id, "owner_gone"),
                              (no_agent_id, "no_agent")):
        firing = await _firing(firing_id)
        assert (firing.status, firing.skip_reason, firing.chat_id) == (FiringStatus.skipped, reason, None)
    assert await _skipped(paused.id) == []  # pausing is a person's choice: nobody is told


async def test_hourly_limit(client, db, world):
    trigger = await make_trigger(db, world, "task_finished", name="Busy")
    now = datetime.now(UTC)
    for _ in range(fire.HOURLY_LIMIT):
        db.add(TriggerFiring(trigger_id=trigger.id, event=trigger.event, subject=SUBJECT, what="x",
                             status=FiringStatus.started, started_at=now))
    await db.commit()
    first = await _pending(db, trigger)
    second = await _pending(db, trigger)

    await fire.tick()
    third = await _pending(db, trigger)
    await fire.tick()

    for firing_id in (first, second, third):
        firing = await _firing(firing_id)
        assert (firing.status, firing.skip_reason) == (FiringStatus.skipped, "rate_limited")
    [note] = await _skipped(trigger.id)  # the owner is the project's manager: one person, told once an hour
    assert (note.user_id, note.kind, note.title) == (world.manager.id, Kind.needs_you, "Trigger Busy skipped")
    assert note.body == fire.SKIP_TEXT["rate_limited"]
    assert note.link == f"/projects/PAY/triggers/{trigger.id}"
    assert note.project_id == uuid.UUID(world.project["id"])


async def test_problem_notifications_follow_the_switch(client, db, world):
    quiet = await make_trigger(db, world, "task_finished", notify_problems=False, any_agent=False)
    loud = await make_trigger(db, world, "task_finished", name="Loud", any_agent=False, owner_id=world.me.id)
    await _pending(db, quiet)
    await _pending(db, loud)

    await fire.tick()

    assert await _skipped(quiet.id) == []
    notes = await _skipped(loud.id)
    # the owner (a member) and the project's manager
    assert sorted(n.user_id for n in notes) == sorted([world.me.id, world.manager.id])
    assert {(n.title, n.body) for n in notes} == {("Trigger Loud skipped", fire.SKIP_TEXT["no_agent"])}


async def test_a_closed_project_drops_pending_firings(client, db, world):
    trigger = await make_trigger(db, world, "task_finished")
    firing_id = await _pending(db, trigger)
    await db.execute(update(Project).where(Project.id == trigger.project_id).values(status=ProjectStatus.finished))
    await db.commit()

    await fire.tick()

    assert await _firing(firing_id) is None
    async with SessionLocal() as s:
        assert (await s.execute(select(Chat))).scalars().all() == []
    assert await _skipped(trigger.id) == []


async def test_firings_already_locked_are_skipped(client, db, world):
    trigger = await make_trigger(db, world, "task_finished")
    locked_id = await _pending(db, trigger)
    free_id = await _pending(db, trigger)

    async with SessionLocal() as other:  # another process is handling this firing
        await other.execute(select(TriggerFiring).where(TriggerFiring.id == locked_id).with_for_update())
        await fire.tick()
        await other.rollback()

    assert (await _firing(locked_id)).status == FiringStatus.pending
    assert (await _firing(free_id)).status == FiringStatus.started
