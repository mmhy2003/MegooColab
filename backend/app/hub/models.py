import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class HubTool(IdMixin, TimestampMixin, Base):
    """An MCP server or a skill in someone's Tool Hub library."""

    __tablename__ = "hub_tools"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="hub_tools_owner_id_name_key"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # "mcp" | "skill"
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    # version: what others see change (setup, files, description); rev: any change, secrets included (machines)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    rev: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    # an MCP's setup (schemas.McpSpec), secret values always ""
    spec: Mapped[dict | None] = mapped_column(JSONB)
    # Fernet(json {slot name: value}); only ever decrypted for the owner's own runner
    secrets_enc: Mapped[str | None] = mapped_column(Text)
    read_only_safe: Mapped[bool] = mapped_column(default=False, server_default=false())
    share_everyone: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_copy: Mapped[bool] = mapped_column(default=False, server_default=false())
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hub_tools.id", ondelete="SET NULL"), index=True)
    source_version: Mapped[int | None] = mapped_column(Integer)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class HubToolShare(IdMixin, Base):
    """One team or one person a tool is shared with."""

    __tablename__ = "hub_tool_shares"
    __table_args__ = (
        CheckConstraint("(team_id IS NULL) <> (user_id IS NULL)", name="hub_tool_shares_one_target_check"),
    )

    tool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hub_tools.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class HubToolFile(IdMixin, Base):
    """A file of a skill."""

    __tablename__ = "hub_tool_files"
    __table_args__ = (UniqueConstraint("tool_id", "path", name="hub_tool_files_tool_id_path_key"),)

    tool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hub_tools.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(255))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int] = mapped_column(Integer)
