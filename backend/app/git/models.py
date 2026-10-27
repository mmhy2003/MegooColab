"""Git provider connections (ADM-1, GIT-1): a read-only token per git host, chosen per project repository."""

import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
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
