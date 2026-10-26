import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.core.db import Base, IdMixin


class EntityKind(StrEnum):
    org = "org"
    team = "team"
    project = "project"
    user = "user"
    agent = "agent"
    product = "product"


class ScopeKind(StrEnum):
    org = "org"
    team = "team"
    project = "project"


class ConclusionKind(StrEnum):
    observed = "observed"
    deduced = "deduced"
    induced = "induced"
    correction = "correction"


class ConclusionStatus(StrEnum):
    active = "active"
    superseded = "superseded"
    deleted = "deleted"


SCOPE_CHECK = (
    "(scope_kind = 'org' AND scope_team_id IS NULL AND scope_project_id IS NULL)"
    " OR (scope_kind = 'team' AND scope_team_id IS NOT NULL AND scope_project_id IS NULL)"
    " OR (scope_kind = 'project' AND scope_project_id IS NOT NULL AND scope_team_id IS NULL)"
)


class ScopeMixin:
    """Who may read a row: everyone (org), a team's members, or a project's members (MEM-7)."""

    scope_kind: Mapped[ScopeKind] = mapped_column(String(10))

    @declared_attr
    def scope_team_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)

    @declared_attr
    def scope_project_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)

    @property
    def scope(self) -> tuple[ScopeKind, uuid.UUID | None]:
        return ScopeKind(self.scope_kind), self.scope_team_id or self.scope_project_id


class MemEntity(IdMixin, Base):
    """A "peer" of the memory (MEM-1). Team, project, user and agent entities point at their row (and go with
    it); the org entity and products stand alone."""

    __tablename__ = "mem_entities"
    __table_args__ = (
        Index("ix_mem_entities_org", "kind", unique=True, postgresql_where=text("kind = 'org'")),
        UniqueConstraint("team_id", name="mem_entities_team_id_key"),
        UniqueConstraint("project_id", name="mem_entities_project_id_key"),
        UniqueConstraint("user_id", name="mem_entities_user_id_key"),
        UniqueConstraint("agent_id", name="mem_entities_agent_id_key"),
    )

    kind: Mapped[EntityKind] = mapped_column(String(10))
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def ref_id(self) -> uuid.UUID | None:
        return self.team_id or self.project_id or self.user_id or self.agent_id


class MemProductProject(Base):
    __tablename__ = "mem_product_projects"

    product_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mem_entities.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)


class MemConclusion(IdMixin, ScopeMixin, Base):
    __tablename__ = "mem_conclusions"
    __table_args__ = (
        CheckConstraint(SCOPE_CHECK, name="mem_conclusions_scope_check"),
        Index("ix_mem_conclusions_entity_status", "entity_id", "status"),
        Index("ix_mem_conclusions_source", "source_kind", "source_id"),
        Index("ix_mem_conclusions_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mem_entities.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String(500))
    kind: Mapped[ConclusionKind] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ConclusionStatus] = mapped_column(String(20), default=ConclusionStatus.active)
    pinned: Mapped[bool] = mapped_column(default=False)
    source_kind: Mapped[str | None] = mapped_column(String(20))
    source_id: Mapped[uuid.UUID | None]
    source_label: Mapped[str | None] = mapped_column(String(200))
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(), deferred=True)
    embedding_model: Mapped[str | None] = mapped_column(String(300))
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, text)", persisted=True), deferred=True
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mem_conclusions.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemPremise(Base):
    """Reasoning chain: `conclusion_id` follows from `premise_id`."""

    __tablename__ = "mem_premises"
    __table_args__ = (CheckConstraint("conclusion_id <> premise_id", name="mem_premises_not_self_check"),)

    conclusion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mem_conclusions.id", ondelete="CASCADE"), primary_key=True
    )
    premise_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mem_conclusions.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class MemSuppression(IdMixin, Base):
    """A conclusion a human deleted or corrected: never learned again from the same source (MEM-8)."""

    __tablename__ = "mem_suppressions"
    __table_args__ = (Index("ix_mem_suppressions_source_entity", "source_kind", "source_id", "entity_id"),)

    source_kind: Mapped[str | None] = mapped_column(String(20))
    source_id: Mapped[uuid.UUID | None]
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mem_entities.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String(500))
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(), deferred=True)
    embedding_model: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemCard(IdMixin, ScopeMixin, Base):
    """An entity's summary, one per scope so it only summarises what that scope's readers may see."""

    __tablename__ = "mem_cards"
    __table_args__ = (
        CheckConstraint(SCOPE_CHECK, name="mem_cards_scope_check"),
        UniqueConstraint(
            "entity_id", "scope_kind", "scope_team_id", "scope_project_id", name="mem_cards_entity_scope_key",
            postgresql_nulls_not_distinct=True,
        ),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mem_entities.id", ondelete="CASCADE"))
    summary_md: Mapped[str] = mapped_column(Text, default="")
    conclusion_ids: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemSourceState(Base):
    __tablename__ = "mem_source_states"

    source_kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    text_hash: Mapped[str] = mapped_column(String(64))
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemDreamRun(IdMixin, Base):
    __tablename__ = "mem_dream_runs"

    trigger: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="running")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    stats: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
