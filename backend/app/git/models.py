"""Git provider connections (ADM-1, GIT-1): a read-only token per git host, chosen per project repository."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class GitKind(StrEnum):
    github = "github"
    gitlab = "gitlab"
    gitea = "gitea"  # Gitea and Forgejo


class GitConnection(IdMixin, TimestampMixin, Base):
    __tablename__ = "git_connections"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[GitKind] = mapped_column(String(20))
    base_url: Mapped[str] = mapped_column(String(300))
    token_enc: Mapped[str] = mapped_column(Text)
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


# a task's pull requests: its own, and a production fix's back-merge into the default branch (Branch from)
PR_MAIN = "main"
PR_BACK_MERGE = "back_merge"


class TaskPullRequest(TimestampMixin, Base):
    """The pull request a task's Finish run opened (GIT-3, GIT-5). Tracked when a connection follows it; an
    untracked one is shown as reported and finishes only by a person's "Mark merged"."""

    __tablename__ = "task_pull_requests"
    __table_args__ = (Index("ix_task_pull_requests_poll", "state", "next_check_at"),)

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True, default=PR_MAIN, server_default=PR_MAIN)
    url: Mapped[str] = mapped_column(String(500))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("git_connections.id", ondelete="SET NULL"), index=True
    )
    state: Mapped[str] = mapped_column(String(20), default="open")  # open | merged | closed
    checks: Mapped[str] = mapped_column(String(20), default="none")  # success | failure | pending | none | unknown
    review: Mapped[str] = mapped_column(String(20), default="none")  # approved | changes_requested | none | unknown
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    head_sha: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(String(30))
    # what the last read could not see (the token lacks the permission): "checks", "review" or "checks,review";
    # those fields are then "unknown"
    limited: Mapped[str | None] = mapped_column(String(30))
    failures: Mapped[int] = mapped_column(default=0, server_default="0")
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GitDelivery(Base):
    """A webhook delivery already handled, by the id its host gives it: a repeat (the host retrying) is ignored.
    Kept for a few days."""

    __tablename__ = "git_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class GitPrLink(Base):
    """A pull request seen opened from a task's branch: later deliveries about it (comments, reviews, the merge),
    which name only its number, find the task here even before MegooColab tracks the pull request."""

    __tablename__ = "git_pr_links"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("git_connections.id", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(String(500), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    url: Mapped[str | None] = mapped_column(Text)
    head_branch: Mapped[str | None] = mapped_column(String(255))
    open: Mapped[bool] = mapped_column(default=True)
