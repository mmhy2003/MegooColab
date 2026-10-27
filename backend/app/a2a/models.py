"""Agent-to-agent questions (BRD §6.6): a question is addressed to a project, not a person."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class QuestionStatus(StrEnum):
    queued = "queued"  # waiting for a runner
    routed = "routed"  # an answering run is queued or running
    draft = "draft"  # waiting for the answering agent's owner
    needs_human = "needs_human"  # routing gave up
    answered = "answered"
    withdrawn = "withdrawn"


OPEN_STATUSES = (QuestionStatus.queued, QuestionStatus.routed, QuestionStatus.draft, QuestionStatus.needs_human)


class Question(IdMixin, Base):
    __tablename__ = "a2a_questions"
    __table_args__ = (
        UniqueConstraint("target_project_id", "number", name="a2a_questions_target_project_id_number_key"),
        Index("ix_a2a_questions_status_created", "status", "created_at"),
    )

    target_project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    number: Mapped[int]
    from_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    asked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    asked_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[QuestionStatus] = mapped_column(String(20), default=QuestionStatus.queued)
    answer_md: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, server_default=text("'[]'::jsonb")
    )
    answer_source: Mapped[str | None] = mapped_column(String(10))
    answered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    answered_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    draft_md: Mapped[str | None] = mapped_column(Text)
    draft_citations: Mapped[list] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, server_default=text("'[]'::jsonb")
    )
    draft_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    redacted: Mapped[bool] = mapped_column(default=False)
    tried_agent_ids: Mapped[list] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, server_default=text("'[]'::jsonb")
    )
    attempts: Mapped[int] = mapped_column(default=0)
    kb_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_documents.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waiting_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NOT-1, once
