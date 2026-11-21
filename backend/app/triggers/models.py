import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class TriggerEvent(StrEnum):
    task_finished = "task_finished"
    task_created = "task_created"
    task_moved = "task_moved"
    task_needs_person = "task_needs_person"
    sprint_started = "sprint_started"
    sprint_completed = "sprint_completed"
    epic_completed = "epic_completed"
    cron_found = "cron_found"
    pr_merged = "pr_merged"


class FiringStatus(StrEnum):
    pending = "pending"  # written by the event, waiting for the trigger loop
    started = "started"  # its chat was started
    skipped = "skipped"  # see SKIP_REASONS


SKIP_REASONS = ("no_agent", "owner_gone", "rate_limited", "paused")
PROMPT_CHARS = 8_000  # a chat message's limit (chats.schemas.MAX_MESSAGE)
WHAT_CHARS = 6_000


class Trigger(IdMixin, Base):
    """When an event of the project happens, a freestyle chat is started with the prompt and what happened."""

    __tablename__ = "triggers"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE", name="triggers_project_id_fkey"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    event: Mapped[TriggerEvent] = mapped_column(String(30))
    # the event's filters (see events.py)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    prompt: Mapped[str] = mapped_column(Text)
    # any free agent of the project, or only the chosen `agent_id` (None once that agent was deleted: no agent)
    any_agent: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL", name="triggers_agent_id_fkey")
    )
    # keep the chat open after the agent replies, or end it
    keep_open: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notify_reply: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notify_problems: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # "runs as": the person who last saved it starts its chats
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="triggers_owner_id_fkey")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="triggers_created_by_fkey")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TriggerFiring(IdMixin, Base):
    """One time a trigger's event happened: started as a chat, or skipped with a reason."""

    __tablename__ = "trigger_firings"
    __table_args__ = (
        UniqueConstraint("chat_id", name="trigger_firings_chat_id_key"),
        Index("ix_trigger_firings_trigger_created", "trigger_id", "created_at"),
        Index("ix_trigger_firings_status", "status"),
    )

    trigger_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("triggers.id", ondelete="CASCADE", name="trigger_firings_trigger_id_fkey")
    )
    event: Mapped[TriggerEvent] = mapped_column(String(30))
    # {kind, label, title, link, note}: the history row
    subject: Mapped[dict] = mapped_column(JSONB)
    # the "What happened" block, at most WHAT_CHARS
    what: Mapped[str] = mapped_column(Text)
    status: Mapped[FiringStatus] = mapped_column(String(10), default=FiringStatus.pending)
    skip_reason: Mapped[str | None] = mapped_column(String(100))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL", name="trigger_firings_agent_id_fkey")
    )
    chat_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chats.id", ondelete="SET NULL", name="trigger_firings_chat_id_fkey")
    )
    keep_open: Mapped[bool] = mapped_column(Boolean, default=False)
    # started by "Try it", not by the event
    tried: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
