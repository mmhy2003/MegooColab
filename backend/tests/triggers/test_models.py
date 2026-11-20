import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.chats.models import Chat, ChatMode
from app.projects.models import Project
from app.triggers.models import FiringStatus, Trigger, TriggerEvent, TriggerFiring


def _trigger(w, **kw) -> Trigger:
    return Trigger(project_id=uuid.UUID(w.project["id"]), name="After a task", event=TriggerEvent.task_finished,
                   prompt="Write the release note", owner_id=w.manager.id, created_by=w.manager.id, **kw)


def _firing(trigger: Trigger, **kw) -> TriggerFiring:
    return TriggerFiring(trigger_id=trigger.id, event=trigger.event, subject={"kind": "task", "label": "PAY-1"},
                         what="Task PAY-1", **kw)


async def test_a_trigger_keeps_its_settings_and_defaults(world, db):
    w = world
    agent_id, manager_id = w.mgr_bot.id, w.manager.id
    db.add(_trigger(w, agent_id=agent_id))
    await db.commit()
    db.expire_all()

    t = (await db.execute(select(Trigger))).scalar_one()
    assert (t.name, t.event, t.prompt) == ("After a task", "task_finished", "Write the release note")
    assert (t.agent_id, t.owner_id, t.created_by) == (agent_id, manager_id, manager_id)
    assert t.config == {}
    assert t.any_agent is True and t.keep_open is False and t.paused is False
    assert t.notify_reply is True and t.notify_problems is True
    assert t.created_at is not None and t.updated_at is not None

    db.add(_firing(t))
    await db.commit()
    db.expire_all()
    f = (await db.execute(select(TriggerFiring))).scalar_one()
    assert f.status == FiringStatus.pending and f.keep_open is False and f.tried is False
    assert f.chat_id is None and f.started_at is None and f.created_at is not None


async def test_deleting_a_trigger_deletes_its_firings(world, db):
    t = _trigger(world)
    db.add(t)
    await db.flush()
    db.add_all([_firing(t), _firing(t)])
    await db.commit()

    await db.delete(t)
    await db.commit()
    db.expire_all()
    assert (await db.execute(select(TriggerFiring))).scalars().all() == []


async def test_a_chat_is_linked_to_one_firing_at_most(world, db):
    w = world
    t = _trigger(w)
    chat = Chat(project_id=uuid.UUID(w.project["id"]), started_by=w.manager.id, title="Release note",
                mode=ChatMode.freestyle)
    db.add_all([t, chat])
    await db.flush()
    db.add(_firing(t, chat_id=chat.id, status=FiringStatus.started))
    await db.commit()

    db.add(_firing(t, chat_id=chat.id, status=FiringStatus.started))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_deleting_the_project_deletes_its_triggers(world, db):
    t = _trigger(world)
    db.add(t)
    await db.flush()
    db.add(_firing(t))
    await db.commit()

    await db.execute(delete(Project).where(Project.id == uuid.UUID(world.project["id"])))
    await db.commit()
    db.expire_all()
    assert (await db.execute(select(Trigger))).scalars().all() == []
    assert (await db.execute(select(TriggerFiring))).scalars().all() == []
