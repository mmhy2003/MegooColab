import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.text import NoNulStr
from app.sprints.models import SprintState


class SprintIn(BaseModel):
    name: NoNulStr = Field(min_length=1, max_length=200)
    goal: NoNulStr = ""
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class SprintPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=200)
    goal: NoNulStr | None = None
    start_date: date | None = None
    end_date: date | None = None


class SprintOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    goal: str
    start_date: date
    end_date: date
    state: SprintState
    completed_at: datetime | None
    committed_points: int | None
    completed_points: int | None


class CompleteIn(BaseModel):
    move_open_to: Literal["backlog"] | uuid.UUID = "backlog"


class TaskSprintIn(BaseModel):
    sprint_id: uuid.UUID | None


class BurndownPoint(BaseModel):
    day: date
    remaining_points: int
    ideal_points: float


class VelocityPoint(BaseModel):
    sprint_id: uuid.UUID
    name: str
    committed_points: int
    completed_points: int
