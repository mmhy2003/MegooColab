import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.projects.models import ColumnCategory, RepoProvider

ProjectKey = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9]{1,9}$")]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class ProjectIn(BaseModel):
    key: ProjectKey
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    team_ids: list[uuid.UUID] = Field(min_length=1)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    sprints_enabled: bool | None = None
    team_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)


class ProjectOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str
    sprints_enabled: bool
    team_ids: list[uuid.UUID]
    created_at: datetime


class ColumnIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: ColumnCategory


class ColumnPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    category: ColumnCategory | None = None


class ColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    position: int
    category: ColumnCategory
    task_count: int = 0


class ColumnOrderIn(BaseModel):
    column_ids: list[uuid.UUID]


class RepoIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    provider: RepoProvider
    default_branch: str = "main"


class RepoPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=1, max_length=1000)
    provider: RepoProvider | None = None
    default_branch: str | None = Field(default=None, min_length=1, max_length=200)


class RepoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    provider: RepoProvider
    default_branch: str


class LabelIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    color: HexColor


class LabelPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    color: HexColor | None = None


class LabelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str
