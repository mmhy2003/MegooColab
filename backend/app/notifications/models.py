"""A notification row per recipient (NOT-1) and per-kind delivery preferences (NOT-2)."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class Kind(StrEnum):
    needs_you = "needs_you"
    assigned = "assigned"
    mentioned = "mentioned"
    agent_offline = "agent_offline"
    question_waiting = "question_waiting"


# (in_app, email, push) when a user has not chosen; push stays off until the person ticks it
DEFAULT_PREFS: dict[Kind, tuple[bool, bool, bool]] = {k: (True, k != Kind.question_waiting, False) for k in Kind}


class Notification(IdMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[Kind] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(500))
    link: Mapped[str] = mapped_column(String(500))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPref(Base):
    __tablename__ = "notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[Kind] = mapped_column(String(30), primary_key=True)
    in_app: Mapped[bool]
    email: Mapped[bool]
    push: Mapped[bool] = mapped_column(default=False, server_default=false())
