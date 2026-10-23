import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.agents.schemas import AgentOut
from app.auth.schemas import UserOut


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class TeamPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str


class TeamSummary(TeamOut):
    member_count: int
    project_count: int


class ProjectRef(BaseModel):
    id: uuid.UUID
    key: str
    name: str


class TeamDetail(TeamOut):
    members: list[UserOut]
    projects: list[ProjectRef]
    agents: list[AgentOut] = []


class MembersIn(BaseModel):
    user_ids: list[uuid.UUID]
