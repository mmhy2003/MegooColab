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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
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
    # pushed to a new machine of its owner's when "install my default set" is on
    in_default_set: Mapped[bool] = mapped_column(default=False, server_default=false())


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


class HubMachine(Base):
    """A machine (runner token) that has had tools pushed: whether a push still waits to be delivered."""

    __tablename__ = "hub_machines"

    token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("personal_access_tokens.id", ondelete="CASCADE"), primary_key=True
    )
    pending: Mapped[bool] = mapped_column(default=False, server_default=false())
    # tool names the next delivery may let replace an entry made by hand
    take_over: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, server_default=text("'[]'::jsonb")
    )
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HubMachineWant(Base):
    """A tool ticked for a machine."""

    __tablename__ = "hub_machine_wants"

    token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("personal_access_tokens.id", ondelete="CASCADE"), primary_key=True
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hub_tools.id", ondelete="CASCADE"), primary_key=True)


class HubInstall(IdMixin, Base):
    """What a machine's runner last reported for one tool in one program."""

    __tablename__ = "hub_installs"
    __table_args__ = (
        UniqueConstraint("token_id", "name", "kind", "program", name="hub_installs_token_id_name_kind_program_key"),
    )

    token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("personal_access_tokens.id", ondelete="CASCADE"), index=True
    )
    tool_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hub_tools.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(10))
    program: Mapped[str] = mapped_column(String(20))
    rev: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class HubPrefs(Base):
    """A person's Tool Hub preferences."""

    __tablename__ = "hub_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    auto_default: Mapped[bool] = mapped_column(default=False, server_default=false())
