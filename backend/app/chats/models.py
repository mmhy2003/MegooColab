import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class ChatStatus(StrEnum):
    open = "open"
    ended = "ended"  # read-only: a new idea starts a new chat


class Chat(IdMixin, Base):
    """A conversation with an agent about one project. Each round of work in it is a task kept off the board
    (`Task.in_chat`) and run by the task workflow; adding a round to the board turns it into an ordinary task."""

    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_project_activity", "project_id", "last_activity_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    started_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[ChatStatus] = mapped_column(String(10), default=ChatStatus.open)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
