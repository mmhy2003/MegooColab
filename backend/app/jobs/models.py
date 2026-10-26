from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class Job(IdMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # dedupe only while queued: an enqueue during a run must not be dropped (the handler re-checks)
        Index("ix_jobs_dedupe_queued", "dedupe_key", unique=True, postgresql_where=text("status = 'queued'")),
        Index("ix_jobs_status_run_after", "status", "run_after"),
    )

    kind: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[JobStatus] = mapped_column(String(20), default=JobStatus.queued)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

