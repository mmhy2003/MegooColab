import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.text import NoNulStr
from app.kb.schemas import TITLE_MAX, Named, SpaceRef

BRIEF_MAX = 20_000
REQUEST_MAX = 20_000
TARGET_TEXT_MAX = 2_000
SOURCES_MAX = 10


class TaskSource(BaseModel):
    kind: Literal["task"]
    key: str = Field(min_length=1, max_length=50)


class DocSource(BaseModel):
    kind: Literal["doc"]
    id: uuid.UUID


class DraftIn(BaseModel):
    space_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    agent_id: uuid.UUID
    brief: NoNulStr = Field(min_length=1, max_length=BRIEF_MAX)
    sources: list[TaskSource | DocSource] = Field(default_factory=list, max_length=SOURCES_MAX)


class DraftEdit(BaseModel):
    title: NoNulStr | None = Field(default=None, max_length=TITLE_MAX)
    # the length limit is checked by the service (422 too_large)
    body_md: NoNulStr | None = None


class AgentChoice(BaseModel):
    agent_id: uuid.UUID


class DraftTarget(BaseModel):
    section: NoNulStr = Field(max_length=TITLE_MAX)
    text: NoNulStr = Field(min_length=1, max_length=TARGET_TEXT_MAX)


class DraftRequest(BaseModel):
    text: NoNulStr = Field(min_length=1, max_length=REQUEST_MAX)
    target: DraftTarget | None = None


class DraftAgentOut(BaseModel):
    id: uuid.UUID
    name: str
    online: bool
    # its runner can work on drafts (drafts/1)
    runner_ok: bool


class Segment(BaseModel):
    kind: Literal["text", "mark"]
    md: str | None = None
    id: int | None = None
    change: Literal["added", "removed", "changed"] | None = None
    request: str | None = None
    old_md: str | None = None
    new_md: str | None = None


class DraftMessageOut(BaseModel):
    id: uuid.UUID
    author: Literal["person", "agent", "system"]
    text: str
    target: DraftTarget | None
    created_at: datetime


class DraftDocument(BaseModel):
    id: uuid.UUID
    latest_revision: int


class DraftOut(BaseModel):
    id: uuid.UUID
    title: str
    body_md: str
    segments: list[Segment]
    open_marks: int
    messages: list[DraftMessageOut]
    agent: DraftAgentOut | None
    space: SpaceRef
    folder_id: uuid.UUID | None
    folder_path: str
    document: DraftDocument | None
    base_revision: int | None
    # writing: the agent is at work; waiting: its turn waits for the agent to come online
    state: Literal["idle", "writing", "waiting"]
    last_activity_at: datetime


class DraftSummary(BaseModel):
    id: uuid.UUID
    title: str
    space: SpaceRef
    document_id: uuid.UUID | None
    agent: Named | None
    last_activity_at: datetime
