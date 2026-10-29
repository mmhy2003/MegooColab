import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.text import NoNulStr
from app.projects.models import ColumnCategory
from app.projects.schemas import LabelOut
from app.tasks.models import LinkKind, Priority, TaskType
from app.workflow.schemas import PullRequestOut, TaskWorkflowOut


class TaskCreate(BaseModel):
    title: NoNulStr = Field(min_length=1, max_length=500)
    type: TaskType = TaskType.task
    description_md: NoNulStr = ""
    column_id: uuid.UUID | None = None
    priority: Priority = Priority.medium
    story_points: int | None = Field(default=None, ge=0, le=1000)
    due_date: date | None = None
    assignee_user_id: uuid.UUID | None = None
    assignee_agent_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    label_ids: list[uuid.UUID] = []
    branch_from: NoNulStr | None = None  # checked by the service (invalid_branch_name); "" means none


class TaskUpdate(BaseModel):
    """Only fields present in the request body are changed (null clears a nullable field)."""

    title: NoNulStr | None = Field(default=None, min_length=1, max_length=500)
    type: TaskType | None = None
    description_md: NoNulStr | None = None
    priority: Priority | None = None
    story_points: int | None = Field(default=None, ge=0, le=1000)
    due_date: date | None = None
    assignee_user_id: uuid.UUID | None = None
    assignee_agent_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    label_ids: list[uuid.UUID] | None = None
    branch_from: NoNulStr | None = None


class AssigneeAgentOut(BaseModel):
    id: uuid.UUID
    name: str
    program: str
    owner_id: uuid.UUID
    status: str


class TaskOut(BaseModel):
    id: uuid.UUID
    key: str
    number: int
    project_id: uuid.UUID
    type: TaskType
    title: str
    description_md: str
    column_id: uuid.UUID
    column_category: ColumnCategory
    position: float
    priority: Priority
    story_points: int | None
    due_date: date | None
    assignee_user_id: uuid.UUID | None
    assignee_agent_id: uuid.UUID | None
    assignee_agent: "AssigneeAgentOut | None" = None
    reporter_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    sprint_id: uuid.UUID | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    labels: list[LabelOut]
    subtask_count: int
    subtask_done_count: int
    links: list["TaskLinkOut"] = []
    watcher_ids: list[uuid.UUID] = []
    workflow: TaskWorkflowOut | None = None
    # projects this task asked questions of that are still open (§6.6 A2A-5)
    waiting_on: list[str] = []
    pull_request: PullRequestOut | None = None  # GIT-5
    branch_from: str | None = None
    start_branch: str | None = None
    back_merge_into: str | None = None
    branch_from_locked: bool = False


class LinkedTask(BaseModel):
    key: str
    title: str
    column_category: ColumnCategory


class TaskLinkOut(BaseModel):
    id: uuid.UUID
    kind: Literal["blocks", "blocked_by", "relates"]
    task: LinkedTask


class MoveIn(BaseModel):
    column_id: uuid.UUID
    before_key: str | None = None
    after_key: str | None = None


class LinkIn(BaseModel):
    target_key: str
    kind: LinkKind
