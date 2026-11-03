import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.text import NoNulStr
from app.projects.models import ColumnCategory, ProjectStatus, RepoProvider
from app.workflow.models import FinishingOption

ProjectKey = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9]{1,9}$")]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class ProjectIn(BaseModel):
    key: ProjectKey
    name: NoNulStr = Field(min_length=1, max_length=200)
    description: NoNulStr = ""
    team_ids: list[uuid.UUID] = Field(min_length=1)


class ProjectPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=200)
    description: NoNulStr | None = None
    sprints_enabled: bool | None = None
    finishing_option: FinishingOption | None = None
    require_human_code_review: bool | None = None
    send_back_on_changes_requested: bool | None = None
    commit_docs_to_repo: bool | None = None
    team_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)


class ProjectOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str
    sprints_enabled: bool
    finishing_option: FinishingOption
    require_human_code_review: bool
    send_back_on_changes_requested: bool
    commit_docs_to_repo: bool
    team_ids: list[uuid.UUID]
    status: ProjectStatus
    created_at: datetime


class ProjectStatusIn(BaseModel):
    status: ProjectStatus


class WorkflowCountOut(BaseModel):
    count: int


class ColumnIn(BaseModel):
    name: NoNulStr = Field(min_length=1, max_length=100)
    category: ColumnCategory


class ColumnPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=100)
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
    name: NoNulStr = Field(min_length=1, max_length=200)
    url: NoNulStr = Field(min_length=1, max_length=1000)
    provider: RepoProvider
    default_branch: NoNulStr = "main"
    connection_id: uuid.UUID | None = None  # GIT-3: the read-only provider connection


class RepoPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=200)
    url: NoNulStr | None = Field(default=None, min_length=1, max_length=1000)
    provider: RepoProvider | None = None
    default_branch: NoNulStr | None = Field(default=None, min_length=1, max_length=200)
    connection_id: uuid.UUID | None = None  # an explicit null unlinks


class RepoChoiceOut(BaseModel):
    path: str
    url: str
    default_branch: str | None


class RepoChoicesOut(BaseModel):
    """A page of the repositories a connection's token can see, to add one to a project."""

    items: list[RepoChoiceOut]
    more: bool


class WebhookOut(BaseModel):
    """A repository's Webhook dialog: where its host posts, and how it is going. Never the secret."""

    url: str
    kind: str
    hook_page_url: str
    status: Literal["not_set_up", "working", "failing"]
    last_at: datetime | None
    installed: bool  # MegooColab made the webhook on the host (Create it for me)
    public_url_is_default: bool  # still the localhost default: a host can't reach it


class WebhookSecretOut(BaseModel):
    secret: str


class WebhookRenewOut(WebhookSecretOut):
    host_updated: bool | None  # None: no webhook made by MegooColab to update


class WebhookInstallOut(BaseModel):
    installed: bool


class RepoConnection(BaseModel):
    id: uuid.UUID
    name: str


class RepoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    provider: RepoProvider
    default_branch: str
    connection: RepoConnection | None = None
    # its own webhook: not_set_up (nothing received at its own address yet), working, or failing (the last delivery's
    # signature was wrong)
    webhook_status: Literal["not_set_up", "working", "failing"] = "not_set_up"
    webhook_last_at: datetime | None = None
    # after a change: the old host would not delete the webhook MegooColab made there (its error code)
    warning: str | None = None


class LabelIn(BaseModel):
    name: NoNulStr = Field(min_length=1, max_length=50)
    color: HexColor


class LabelPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=50)
    color: HexColor | None = None


class LabelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str
