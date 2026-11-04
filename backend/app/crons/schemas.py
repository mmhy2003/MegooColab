from datetime import datetime

from pydantic import BaseModel, Field

from app.core.text import NoNulStr


class PreviewIn(BaseModel):
    schedule: NoNulStr = Field(max_length=200)
    timezone: NoNulStr = Field(max_length=64)


class Preview(BaseModel):
    ok: bool
    error: str | None
    description: str | None
    next: list[datetime]
