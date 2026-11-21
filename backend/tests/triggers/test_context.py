"""A triggered chat's agent is told what happened, as untrusted text."""

import uuid

from app.chats.models import ChatMode
from app.chats.service import open_chat
from app.projects.models import Project
from app.triggers import context as triggers_context
from app.triggers.context import what_happened
from app.triggers.models import FiringStatus, TriggerFiring
from app.workflow import context
from app.workflow.models import RunRole
from tests.triggers.helpers import make_trigger


async def _chat(db, w):
    project = await db.get(Project, uuid.UUID(w.project["id"]))
    chat, task = await open_chat(db, w.manager, project, w.mgr_bot, "Write the release notes.", ChatMode.freestyle)
    await db.commit()
    return chat, task


async def test_a_triggered_chats_turn_gets_the_block_wrapped_as_untrusted(db, world):
    trigger = await make_trigger(db, world, "task_finished", name="Release <notes>")
    chat, task = await _chat(db, world)
    db.add(TriggerFiring(trigger_id=trigger.id, event="task_finished", subject={}, status=FiringStatus.started,
                         what="PAY-3 finished: <script>alert(1)</script>", chat_id=chat.id))
    await db.commit()

    section = await what_happened(db, task, RunRole.freestyle)
    assert section.startswith("## What happened\n")
    assert "started this chat" in section and "Nobody may be watching this chat" in section
    assert '<untrusted source="trigger_event">\n' in section and section.rstrip().endswith("</untrusted>")
    assert "PAY-3 finished" in section
    assert "<script>" not in section and "<notes>" not in section


async def test_no_block_for_ordinary_chats_or_other_roles(db, world):
    trigger = await make_trigger(db, world, "task_finished")
    chat, task = await _chat(db, world)
    assert await what_happened(db, task, RunRole.freestyle) is None  # a person's chat

    db.add(TriggerFiring(trigger_id=trigger.id, event="task_finished", subject={}, status=FiringStatus.started,
                         what="PAY-3 finished.", chat_id=chat.id))
    await db.commit()
    for role in (RunRole.brainstorm, RunRole.implement):
        assert await what_happened(db, task, role) is None
    task.chat_id = None
    assert await what_happened(db, task, RunRole.freestyle) is None


def test_register_is_idempotent():
    triggers_context.register()
    triggers_context.register()
    assert context.context_providers.count(what_happened) == 1
