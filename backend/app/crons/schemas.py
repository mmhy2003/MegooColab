import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.text import NoNulStr
from app.kb.schemas import Named


class PreviewIn(BaseModel):
    schedule: NoNulStr = Field(max_length=200)
    timezone: NoNulStr = Field(max_length=64)


class Preview(BaseModel):
    ok: bool
    error: str | None
    description: str | None
    next: list[datetime]


CronModeName = Literal["report", "tasks", "kb"]


class CronIn(BaseModel):
    name: NoNulStr = Field(min_length=1, max_length=100)
    prompt: NoNulStr = Field(min_length=1, max_length=20_000)
    schedule: NoNulStr = Field(max_length=200)
    timezone: NoNulStr = Field(max_length=64)
    agent_id: uuid.UUID | None = None
    mode: CronModeName = "report"
    kb_title: NoNulStr | None = Field(default=None, max_length=200)
    notify_findings: bool = True
    notify_every: bool = False
    notify_failures: bool = True


class CronPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=100)
    prompt: NoNulStr | None = Field(default=None, min_length=1, max_length=20_000)
    schedule: NoNulStr | None = Field(default=None, max_length=200)
    timezone: NoNulStr | None = Field(default=None, max_length=64)
    # "any free agent" is an explicit null: `agent_id` given as null clears the choice
    agent_id: uuid.UUID | None = None
    mode: CronModeName | None = None
    kb_title: NoNulStr | None = Field(default=None, max_length=200)
    notify_findings: bool | None = None
    notify_every: bool | None = None
    notify_failures: bool | None = None


class CronRunOut(BaseModel):
    id: uuid.UUID
    scheduled_at: datetime
    status: Literal["queued", "running", "done", "failed", "skipped"]
    skip_reason: str | None
    agent: Named | None
    started_at: datetime | None
    finished_at: datetime | None
    report: dict | None
    commit: str | None
    tasks_created: int


class CronOut(BaseModel):
    id: uuid.UUID
    project_key: str
    name: str
    prompt: str
    schedule: str
    timezone: str
    description: str
    # any free agent of the project; false with no agent: the chosen agent was deleted
    any_agent: bool
    agent: Named | None
    mode: CronModeName
    kb_title: str | None
    kb_document_id: uuid.UUID | None
    notify_findings: bool
    notify_every: bool
    notify_failures: bool
    paused: bool
    next_run_at: datetime | None
    last_run: CronRunOut | None
    created_by: Named | None
    created_at: datetime
