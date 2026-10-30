import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.text import NoNulStr


class PushKeyOut(BaseModel):
    public_key: str


class SubscriptionKeys(BaseModel):
    p256dh: NoNulStr = Field(min_length=1, max_length=200)
    auth: NoNulStr = Field(min_length=1, max_length=100)


class PushSubscriptionIn(BaseModel):
    """What the browser's PushSubscription.toJSON() gives."""

    endpoint: NoNulStr = Field(min_length=1, max_length=1000)
    keys: SubscriptionKeys


class PushSubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    endpoint: str
    name: str
    created_at: datetime
