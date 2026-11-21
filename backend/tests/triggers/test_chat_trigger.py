"""A chat is opened from one place, and a chat started by a trigger shows that trigger."""

import uuid

from app.chats.models import Chat, ChatMode
from app.chats.service import open_chat
from app.projects.models import Project
from app.triggers.models import FiringStatus, TriggerFiring
from tests.chats.helpers import start
from tests.triggers.helpers import make_trigger


async def test_an_ordinary_chat_has_no_trigger(client, db, world):
    chat = await start(client, mode="freestyle")
    assert chat["trigger"] is None
    r = await client.get(f"/api/chats/{chat['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["trigger"] is None


async def test_open_chat_uses_the_given_title_and_message(client, db, world):
    project = await db.get(Project, uuid.UUID(world.project["id"]))
    message = "Check the release notes.\n\nWhat happened: PAY-3 finished."
    chat, task = await open_chat(db, world.manager, project, world.mgr_bot, message, ChatMode.freestyle,
                                 title="Release notes · PAY-3")
    await db.commit()
    assert chat.title == "Release notes · PAY-3" and task.title == "Release notes · PAY-3"
    assert task.description_md == message and task.chat_id == chat.id and task.chat_round == 1
    assert chat.started_by == world.manager.id and chat.agent_id == world.mgr_bot.id
    assert chat.mode == ChatMode.freestyle

    untitled, _ = await open_chat(db, world.manager, project, world.mgr_bot, "\nTidy up\nthe board", ChatMode.freestyle)
    assert untitled.title == "Tidy up"
    long, _ = await open_chat(db, world.manager, project, world.mgr_bot, message, ChatMode.freestyle, title="x" * 300)
    assert long.title == "x" * 200


async def test_a_chat_linked_to_a_firing_shows_its_trigger(client, db, world):
    trigger = await make_trigger(db, world, "task_finished", name="Release notes")
    trigger_id = trigger.id
    chat = await start(client, mode="freestyle")
    db.add(TriggerFiring(trigger_id=trigger_id, event="task_finished", subject={}, what="PAY-3 finished.",
                         status=FiringStatus.started, chat_id=uuid.UUID(chat["id"]), keep_open=True))
    await db.commit()

    r = await client.get(f"/api/chats/{chat['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["trigger"] == {"id": str(trigger_id), "name": "Release notes", "what": "PAY-3 finished.",
                                   "keep_open": True}

    await db.delete(trigger)
    await db.commit()
    r = await client.get(f"/api/chats/{chat['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["trigger"] is None
    assert await db.get(Chat, uuid.UUID(chat["id"])) is not None
