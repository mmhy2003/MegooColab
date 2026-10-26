import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.text import NoNulStr
from app.kb.models import SpaceKind

TITLE_MAX = 200
SUMMARY_MAX = 200
FOLDER_NAME = Field(min_length=1, max_length=100, pattern=r"^[^/\\]+$")


class SpaceRef(BaseModel):
    id: uuid.UUID
    kind: SpaceKind
    name: str


class SpaceOut(SpaceRef):
    team_id: uuid.UUID | None
    project_id: uuid.UUID | None
    can_write: bool


class FolderIn(BaseModel):
    parent_id: uuid.UUID | None = None
    name: NoNulStr = FOLDER_NAME


class FolderPatch(BaseModel):
    name: NoNulStr = FOLDER_NAME


class FolderOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str


class TreeDoc(BaseModel):
    id: uuid.UUID
    folder_id: uuid.UUID | None
    title: str
    latest_revision: int
    updated_at: datetime


class TreeOut(BaseModel):
    folders: list[FolderOut]
    documents: list[TreeDoc]


class DocumentIn(BaseModel):
    folder_id: uuid.UUID | None = None
    title: NoNulStr = Field(min_length=1, max_length=TITLE_MAX)
    # the length limit is checked by the service (422 too_large)
    body_md: NoNulStr = ""
    summary: NoNulStr | None = Field(default=None, max_length=SUMMARY_MAX)


class DocumentUpdate(BaseModel):
    base_revision: int = Field(ge=1)
    title: NoNulStr | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    body_md: NoNulStr | None = None
    summary: NoNulStr | None = Field(default=None, max_length=SUMMARY_MAX)


class MoveIn(BaseModel):
    space_id: uuid.UUID
    folder_id: uuid.UUID | None = None


class Named(BaseModel):
    id: uuid.UUID
    name: str


class Author(BaseModel):
    user: Named | None
    agent: Named | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    space: SpaceRef
    folder_id: uuid.UUID | None
    path: str
    title: str
    body_md: str
    latest_revision: int
    created_by: uuid.UUID | None
    updated_at: datetime
    updated_by: Author
    can_write: bool
    can_delete: bool


class RevisionSummary(BaseModel):
    revision: int
    title: str
    summary: str | None
    author: Author
    created_at: datetime


class RevisionOut(RevisionSummary):
    body_md: str


class DocRef(BaseModel):
    id: uuid.UUID
    title: str
    space: SpaceRef


class ResolveIn(BaseModel):
    doc_ids: list[uuid.UUID] = Field(max_length=200)


class Resolved(BaseModel):
    title: str | None
    readable: bool


class SearchHit(BaseModel):
    document_id: uuid.UUID
    space: SpaceRef
    title: str
    path: str
    snippet: str
    score: float


class SearchOut(BaseModel):
    semantic: bool
    results: list[SearchHit]
