import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class ColumnCategory(StrEnum):
    before = "before"
    working = "working"
    review = "review"
    done = "done"


class RepoProvider(StrEnum):
    github = "github"
    gitlab = "gitlab"
    gitea = "gitea"
    plain = "plain"


DEFAULT_COLUMNS: list[tuple[str, ColumnCategory]] = [
    ("Backlog", ColumnCategory.before),
    ("To Do", ColumnCategory.before),
    ("In Progress", ColumnCategory.working),
    ("In Review", ColumnCategory.review),
    ("Done", ColumnCategory.done),
]


class Project(IdMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    key: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    sprints_enabled: Mapped[bool] = mapped_column(default=True)
    next_task_number: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProjectTeam(Base):
    __tablename__ = "project_teams"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class BoardColumn(IdMixin, Base):
    __tablename__ = "board_columns"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int]
    category: Mapped[ColumnCategory] = mapped_column(String(20))


class ProjectRepository(IdMixin, TimestampMixin, Base):
    __tablename__ = "project_repositories"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(1000))
    provider: Mapped[RepoProvider] = mapped_column(String(20))
    default_branch: Mapped[str] = mapped_column(String(200), default="main")


class Label(IdMixin, Base):
    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))
    color: Mapped[str] = mapped_column(String(7))
