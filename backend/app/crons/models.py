import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class CronMode(StrEnum):
    report = "report"  # the report is kept, people are told
    tasks = "tasks"  # and it may open tasks for real problems
    kb = "kb"  # and it rewrites one Knowledge Base document


class CronRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"


class Cron(IdMixin, Base):
    """A prompt one of a project's agents runs at each time of its schedule, exactly once."""

    __tablename__ = "crons"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prompt: Mapped[str] = mapped_column(Text)
    schedule: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64))
    # any free agent of the project, or only the chosen `agent_id` (None once that agent was deleted: no agent)
    any_agent: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    mode: Mapped[CronMode] = mapped_column(String(10), default=CronMode.report)
    # kb mode: the document it keeps, followed by id (None until the first run, or once deleted)
    kb_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_documents.id", ondelete="SET NULL"))
    kb_title: Mapped[str | None] = mapped_column(String(200))
    notify_findings: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_every: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_failures: Mapped[bool] = mapped_column(Boolean, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # when it is next due; None while paused
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CronRun(IdMixin, Base):
    """One scheduled time of a cron: its row is the claim (unique per time), so the time runs exactly once."""

    __tablename__ = "cron_runs"
    __table_args__ = (
        UniqueConstraint("cron_id", "scheduled_at", name="cron_runs_cron_time_key"),
        Index("ix_cron_runs_cron_scheduled", "cron_id", "scheduled_at"),
    )

    cron_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crons.id", ondelete="CASCADE"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[CronRunStatus] = mapped_column(String(10), default=CronRunStatus.queued)
    # previous_running | missed | no_agent | no_agent_online | the run's failure reason
    skip_reason: Mapped[str | None] = mapped_column(String(100))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    # {summary, findings: [{title, detail, task_key?, created?}], checked, nothing_new, notes: [], timed_out?}
    report: Mapped[dict | None] = mapped_column(JSONB)
    # the commit the run worked on
    commit: Mapped[str | None] = mapped_column(String(64))
    tasks_created: Mapped[int] = mapped_column(Integer, default=0)
    # when the scheduler claimed the time: the wait for an agent counts from here (a time run late after downtime
    # still gets its full wait)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
