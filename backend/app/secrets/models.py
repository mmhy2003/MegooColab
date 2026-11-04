import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class Secret(IdMixin, Base):
    """A credential agents get as an environment variable: a person's own, or a project's. Its value is encrypted
    (app.core.crypto) and never leaves the server except in a run's start, to the agent's runner."""

    __tablename__ = "secrets"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (project_id IS NULL)", name="secrets_owner_check"),
        Index("secrets_user_name_key", "user_id", "name", unique=True, postgresql_where=text("user_id IS NOT NULL")),
        Index("secrets_project_name_key", "project_id", "name", unique=True,
              postgresql_where=text("project_id IS NOT NULL")),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(1000))
    value_enc: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    value_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
