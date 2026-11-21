import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.text import NoNulStr
from app.kb.schemas import Named
from app.triggers.models import PROMPT_CHARS


class TriggerIn(BaseModel):
    name: NoNulStr = Field(min_length=1, max_length=100)
    event: NoNulStr = Field(max_length=30)  # checked by events.spec: invalid_event
    config: dict = {}
    prompt: NoNulStr = Field(min_length=1, max_length=PROMPT_CHARS)
    agent_id: uuid.UUID | None = None  # None: any free agent
    keep_open: bool = False
    notify_reply: bool = True
    notify_problems: bool = True


class TriggerPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=100)
    event: NoNulStr | None = Field(default=None, max_length=30)
    config: dict | None = None
    prompt: NoNulStr | None = Field(default=None, min_length=1, max_length=PROMPT_CHARS)
    # "any free agent" is an explicit null: `agent_id` given as null clears the choice
    agent_id: uuid.UUID | None = None
    keep_open: bool | None = None
    notify_reply: bool | None = None
    notify_problems: bool | None = None


class FiringSubject(BaseModel):
    kind: str
    label: str
    title: str
    link: str | None
    note: str


FiringResult = Literal["starting", "waiting_agent", "working", "question", "replied", "failed", "skipped"]


class FiringOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    subject: FiringSubject
    agent: Named | None
    chat_id: uuid.UUID | None
    result: FiringResult
    # the reply's first lines, the question, the failure's reason or the skip reason
    excerpt: str | None


class TriggerOut(BaseModel):
    id: uuid.UUID
    project_key: str
    name: str
    event: str
    config: dict
    prompt: str
    # any free agent of the project; false with no agent: the chosen agent was deleted
    any_agent: bool
    agent: Named | None
    keep_open: bool
    notify_reply: bool
    notify_problems: bool
    paused: bool
    owner: Named | None  # "runs as"
    created_by: Named | None
    created_at: datetime
    updated_at: datetime
    broken: Literal["column_deleted", "label_deleted", "cron_deleted"] | None
    last_firing: FiringOut | None
    try_subject: str | None  # "Try it on PAY-12": the newest match's label, None when nothing matches
