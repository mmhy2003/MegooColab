import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class KbDraft(IdMixin, Base):
    """A person's unsaved draft of a Knowledge Base document, written with one of their agents. Only its person sees
    it; nothing reaches the Knowledge Base until they save it."""

    __tablename__ = "kb_drafts"
    __table_args__ = (
        # one draft per person per existing document; new-document drafts are unlimited
        Index(
            "kb_drafts_user_document_key", "user_id", "document_id", unique=True,
            postgresql_where=text("document_id IS NOT NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # None once the agent was deleted: the person picks another one
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_spaces.id", ondelete="CASCADE"))
    folder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_folders.id", ondelete="SET NULL"))
    # the document being improved, or None for a new document
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"))
    # the document's revision the draft started from (or was last brought up to)
    base_revision: Mapped[int | None]
    title: Mapped[str] = mapped_column(String(200), default="")
    body_md: Mapped[str] = mapped_column(Text, default="")
    brief: Mapped[str] = mapped_column(Text)
    # what the person pointed the agent to, read with their access when the draft started:
    # [{"kind": "task"|"doc", "ref", "title", "text"}]
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    # the last agent turn's changes while any is unreviewed (see blocks.new_turn), else None
    turn: Mapped[dict | None] = mapped_column(JSONB)
    # the agent's session, resumed by the next turn
    session_ref: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbDraftMessage(IdMixin, Base):
    """One line of a draft's conversation: the person's request, the agent's reply, or a note from MegooColab."""

    __tablename__ = "kb_draft_messages"

    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_drafts.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(10))  # person | agent | system
    text: Mapped[str] = mapped_column(Text)
    # what a request was aimed at: {"section", "text"}
    target: Mapped[dict | None] = mapped_column(JSONB)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
