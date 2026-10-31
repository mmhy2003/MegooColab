import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class AgentProgram(StrEnum):
    claude_code = "claude_code"
    codex = "codex"


class AnswerMode(StrEnum):
    auto = "auto"
    manual = "manual"


class Agent(IdMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    program: Mapped[AgentProgram] = mapped_column(String(20))
    answer_mode: Mapped[AnswerMode] = mapped_column(String(20), default=AnswerMode.manual)
    max_concurrent_runs: Mapped[int] = mapped_column(default=1)
    # the token of the machine whose runner runs this agent; None: unlinked, so no runner takes it
    runner_token_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("personal_access_tokens.id", ondelete="SET NULL"), index=True
    )
    # the model its sessions start on, as the owner typed or picked it; None: the program's own default
    model: Mapped[str | None] = mapped_column(String(100))
    # the models its program offered on its last run ([{value, name}]), for the owner to pick from
    known_models: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentBinding(IdMixin, Base):
    __tablename__ = "agent_bindings"
    __table_args__ = (UniqueConstraint("agent_id", "project_id"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    local_path: Mapped[str] = mapped_column(String(1000))
