import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin

# full-text indexes the title and the first FTS_BODY_CHARS of the body: a tsvector is capped at 1 MB
FTS_BODY_CHARS = 100_000


class SpaceKind(StrEnum):
    org = "org"
    team = "team"
    project = "project"


class FilingKind(StrEnum):
    design = "design"
    plan = "plan"
    review = "review"


class KbSpace(IdMixin, Base):
    __tablename__ = "kb_spaces"
    __table_args__ = (
        Index("ix_kb_spaces_org", "kind", unique=True, postgresql_where=text("kind = 'org'")),
        CheckConstraint(
            "(kind = 'org' AND team_id IS NULL AND project_id IS NULL)"
            " OR (kind = 'team' AND team_id IS NOT NULL AND project_id IS NULL)"
            " OR (kind = 'project' AND project_id IS NOT NULL AND team_id IS NULL)",
            name="kb_spaces_owner_check",
        ),
    )

    kind: Mapped[SpaceKind] = mapped_column(String(20))
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), unique=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbFolder(IdMixin, Base):
    __tablename__ = "kb_folders"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "parent_id", "name", name="kb_folders_space_parent_name_key", postgresql_nulls_not_distinct=True
        ),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_spaces.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_folders.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbDocument(IdMixin, Base):
    __tablename__ = "kb_documents"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "folder_id", "title", name="kb_documents_space_folder_title_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_kb_documents_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_spaces.id", ondelete="CASCADE"), index=True)
    # a deleted folder's documents are moved up by the service before the folder goes
    folder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_folders.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    # copy of the latest revision's body, for the generated search column
    body_md: Mapped[str] = mapped_column(Text, default="")
    latest_revision: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A') || "
            f"setweight(to_tsvector('simple'::regconfig, left(coalesce(body_md, ''), {FTS_BODY_CHARS})), 'B')",
            persisted=True,
        ),
        deferred=True,
    )


class KbRevision(IdMixin, Base):
    __tablename__ = "kb_revisions"
    __table_args__ = (UniqueConstraint("document_id", "revision", name="kb_revisions_document_id_revision_key"),)

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"))
    revision: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    body_md: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(String(200))
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbLink(IdMixin, Base):
    __tablename__ = "kb_links"
    __table_args__ = (
        CheckConstraint(
            "(target_task_id IS NULL) <> (target_document_id IS NULL)", name="kb_links_one_target_check"
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True)
    target_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    target_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True
    )


class KbChunk(IdMixin, Base):
    __tablename__ = "kb_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int]
    ordinal: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    # no fixed dimension: the model can change; only vectors of the current model are compared
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(), deferred=True)
    embedding_model: Mapped[str | None] = mapped_column(String(300))


class KbFiling(Base):
    __tablename__ = "kb_filings"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[FilingKind] = mapped_column(String(20), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"))
