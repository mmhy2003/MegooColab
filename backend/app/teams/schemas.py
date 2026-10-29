import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.agents.schemas import AgentOut
from app.auth.schemas import UserOut
from app.core.text import NoNulStr


class TeamIn(BaseModel):
    name: NoNulStr = Field(min_length=1, max_length=200)
    description: NoNulStr = ""


class TeamPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=200)
    description: NoNulStr | None = None


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str


class TeamSummary(TeamOut):
    member_count: int
    project_count: int
    is_member: bool = False  # the caller belongs to it (a manager may only attach their own teams)


class ProjectRef(BaseModel):
    id: uuid.UUID
    key: str
    name: str


class TeamDetail(TeamOut):
    members: list[UserOut]
    projects: list[ProjectRef]  # the ones the caller can see
    project_count: int = 0  # all of them: a team with projects cannot be deleted
    agents: list[AgentOut] = []


class MembersIn(BaseModel):
    user_ids: list[uuid.UUID]
