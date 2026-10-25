import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin
from app.workflow.models import RunRole, Stage


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


ACTIVE_STATUSES = (RunStatus.queued, RunStatus.running)


class RunPolicy(StrEnum):
    read_only = "read_only"
    workspace = "workspace"


class AgentRun(IdMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_agent_status", "agent_id", "status"),)

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    policy: Mapped[RunPolicy] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[RunStatus] = mapped_column(String(20), default=RunStatus.queued)
    reason: Mapped[str | None] = mapped_column(String(100))
    summary: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_seq: Mapped[int] = mapped_column(default=0)
    workflow_role: Mapped[RunRole | None] = mapped_column(String(20))
    stage: Mapped[Stage | None] = mapped_column(String(20))
    step: Mapped[int | None]
    session_ref: Mapped[str | None] = mapped_column(String(200))
    resume_session_ref: Mapped[str | None] = mapped_column(String(200))
    resume_prompt: Mapped[str | None] = mapped_column(Text)
    mcp_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    methodology_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("methodology_versions.id", ondelete="SET NULL")
    )
    git_before: Mapped[dict | None] = mapped_column(JSONB)
    git_after: Mapped[dict | None] = mapped_column(JSONB)
    # build runs: the agent's last complete_step report {summary, tests_passed, test_command}
    step_result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
