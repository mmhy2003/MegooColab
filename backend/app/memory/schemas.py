import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.text import NoNulStr


class MemScopeOut(BaseModel):
    kind: str
    id: uuid.UUID | None
    name: str


class MemSourceOut(BaseModel):
    kind: str
    label: str
    link: str | None


class ConclusionOut(BaseModel):
    id: uuid.UUID
    entity_id: uuid.UUID
    entity_name: str
    text: str
    kind: str
    confidence: float | None
    status: str
    pinned: bool
    scope: MemScopeOut
    source: MemSourceOut | None
    created_at: datetime
    can_edit: bool


class MemEntityOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    description: str
    conclusion_count: int


class MemCardOut(BaseModel):
    scope: MemScopeOut
    summary_md: str
    refreshed_at: datetime


class MemEntityDetail(BaseModel):
    entity: MemEntityOut
    cards: list[MemCardOut]
    project_ids: list[uuid.UUID] = []


class ConclusionPage(BaseModel):
    items: list[ConclusionOut]
    next_cursor: str | None


class ChainNode(BaseModel):
    conclusion: ConclusionOut
    premises: list["ChainNode"] = []


class ConclusionDetail(BaseModel):
    conclusion: ConclusionOut
    premises: list[ChainNode]
    derived: list[ConclusionOut]


class CorrectIn(BaseModel):
    text: NoNulStr = Field(min_length=1, max_length=500)


class PinIn(BaseModel):
    pinned: bool


class AskIn(BaseModel):
    question: NoNulStr = Field(min_length=1, max_length=1000)
    project_key: str | None = None


class AskOut(BaseModel):
    answer_md: str
    cited: list[ConclusionOut]


class ProductIn(BaseModel):
    name: NoNulStr = Field(min_length=1, max_length=100)
    description: NoNulStr = Field(default="", max_length=2000)
    project_ids: list[uuid.UUID] = []


class ProductPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=100)
    description: NoNulStr | None = Field(default=None, max_length=2000)
    project_ids: list[uuid.UUID] | None = None


class DreamRunOut(BaseModel):
    id: uuid.UUID
    trigger: str
    status: str
    stats: dict
    error: str | None
    started_at: datetime
    finished_at: datetime | None
