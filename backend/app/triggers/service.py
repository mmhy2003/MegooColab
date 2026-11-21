"""Triggers: the firing behind a chat."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.schemas import ChatTrigger
from app.triggers.models import Trigger, TriggerFiring


async def firing_of_chat(db: AsyncSession, chat_id: uuid.UUID) -> TriggerFiring | None:
    """The firing that started the chat, if a trigger did."""
    return await db.scalar(select(TriggerFiring).where(TriggerFiring.chat_id == chat_id))


async def chat_trigger(db: AsyncSession, chat_id: uuid.UUID) -> ChatTrigger | None:
    """The trigger that started the chat and what happened; None for a person's chat, or once the trigger is
    deleted (its firings go with it)."""
    row = (await db.execute(
        select(Trigger.id, Trigger.name, TriggerFiring.what, TriggerFiring.keep_open)
        .join(Trigger, Trigger.id == TriggerFiring.trigger_id)
        .where(TriggerFiring.chat_id == chat_id)
    )).first()
    return ChatTrigger(id=row.id, name=row.name, what=row.what, keep_open=row.keep_open) if row else None
