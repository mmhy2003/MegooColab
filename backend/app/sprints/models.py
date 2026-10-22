import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class SprintState(StrEnum):
    planned = "planned"
    active = "active"
    completed = "completed"


class Sprint(IdMixin, TimestampMixin, Base):
    __tablename__ = "sprints"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    state: Mapped[SprintState] = mapped_column(String(20), default=SprintState.planned)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_points: Mapped[int | None]
    completed_points: Mapped[int | None]


class SprintSnapshot(IdMixin, Base):
    __tablename__ = "sprint_snapshots"
    __table_args__ = (UniqueConstraint("sprint_id", "day"),)

    sprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sprints.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    total_points: Mapped[int]
    remaining_points: Mapped[int]
