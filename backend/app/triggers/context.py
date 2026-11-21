"""What a triggered chat's agent is told: the event that started the chat, as untrusted text."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.models import Task
from app.triggers.service import chat_trigger
from app.workflow import context
from app.workflow.models import RunRole

WHAT_HAPPENED = ("## What happened\n\nA trigger of this project (\"{name}\") started this chat when the event below "
                 "happened. Nobody may be watching this chat: do what the first message asks, and say in your reply "
                 "what you did.\n\n{block}")


async def what_happened(db: AsyncSession, task: Task, role: RunRole) -> str | None:
    """A freestyle turn of a chat a trigger started gets the firing's text; any other turn gets nothing."""
    if role != RunRole.freestyle or task.chat_id is None:
        return None
    found = await chat_trigger(db, task.chat_id)
    if found is None:
        return None
    # the name is a manager's own words, escaped so it cannot open a fake wrapper; the event text is untrusted
    return WHAT_HAPPENED.format(name=context._escape(found.name),
                                block=context.wrap_untrusted("trigger_event", found.what))


def register() -> None:
    if what_happened not in context.context_providers:
        context.context_providers.append(what_happened)
