import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.notifications.models import Kind


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: Kind
    title: str
    body: str
    link: str
    task_id: uuid.UUID | None
    project_id: uuid.UUID | None
    created_at: datetime
    read_at: datetime | None


class UnreadCount(BaseModel):
    count: int


class NotificationPrefIO(BaseModel):
    kind: Kind
    in_app: bool
    email: bool
