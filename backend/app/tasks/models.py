import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class TaskType(StrEnum):
    epic = "epic"
    story = "story"
    task = "task"
    bug = "bug"
    subtask = "subtask"


class Priority(StrEnum):
    lowest = "lowest"
    low = "low"
    medium = "medium"
    high = "high"
    highest = "highest"


task_labels = Table(
    "task_labels",
    Base.metadata,
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("label_id", ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True, index=True),
)

task_watchers = Table(
    "task_watchers",
    Base.metadata,
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class Task(IdMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("project_id", "number"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    number: Mapped[int]
    type: Mapped[TaskType] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(500))
    description_md: Mapped[str] = mapped_column(Text, default="")
    column_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("board_columns.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[float] = mapped_column(Float)
    priority: Mapped[Priority] = mapped_column(String(20), default=Priority.medium)
    story_points: Mapped[int | None]
    due_date: Mapped[date | None] = mapped_column(Date)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    sprint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sprints.id", ondelete="SET NULL"), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LinkKind(StrEnum):
    blocks = "blocks"
    relates = "relates"


class TaskLink(IdMixin, Base):
    __tablename__ = "task_links"
    __table_args__ = (UniqueConstraint("source_id", "target_id", "kind"),)

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[LinkKind] = mapped_column(String(20))


class TaskEvent(IdMixin, Base):
    __tablename__ = "task_events"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(50))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Comment(IdMixin, Base):
    __tablename__ = "comments"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body_md: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Attachment(IdMixin, Base):
    __tablename__ = "attachments"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(200))
    size: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(200))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
