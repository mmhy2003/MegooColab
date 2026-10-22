import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.projects.models import ColumnCategory
from app.projects.schemas import LabelOut
from app.tasks.models import Priority, TaskType


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    type: TaskType = TaskType.task
    description_md: str = ""
    column_id: uuid.UUID | None = None
    priority: Priority = Priority.medium
    story_points: int | None = Field(default=None, ge=0, le=1000)
    due_date: date | None = None
    assignee_user_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    label_ids: list[uuid.UUID] = []


class TaskUpdate(BaseModel):
    """Only fields present in the request body are changed (null clears a nullable field)."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    type: TaskType | None = None
    description_md: str | None = None
    priority: Priority | None = None
    story_points: int | None = Field(default=None, ge=0, le=1000)
    due_date: date | None = None
    assignee_user_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    label_ids: list[uuid.UUID] | None = None


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
    reporter_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    sprint_id: uuid.UUID | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    labels: list[LabelOut]
    subtask_count: int
    subtask_done_count: int
