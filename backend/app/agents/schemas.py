import uuid
from typing import Annotated

from pydantic import BaseModel, Field

from app.agents.models import AgentProgram, AnswerMode
from app.auth.schemas import UserOut
from app.core.text import NoNulStr

MaxRuns = Annotated[int, Field(ge=1, le=3)]


class AgentIn(BaseModel):
    program: AgentProgram
    name: NoNulStr | None = Field(default=None, max_length=200)
    answer_mode: AnswerMode = AnswerMode.manual
    max_concurrent_runs: MaxRuns = 1


class AgentPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=200)
    answer_mode: AnswerMode | None = None
    max_concurrent_runs: MaxRuns | None = None


class BindingIn(BaseModel):
    project_ref: NoNulStr = Field(min_length=1, max_length=64)
    local_path: NoNulStr = Field(max_length=1000)


class BindingsIn(BaseModel):
    bindings: list[BindingIn]


class BindingOut(BaseModel):
    project_id: uuid.UUID
    project_key: str
    local_path: str | None


class AgentOut(BaseModel):
    id: uuid.UUID
    name: str
    program: AgentProgram
    answer_mode: AnswerMode
    max_concurrent_runs: int
    owner: UserOut
    status: str
    problems: list[str] = []
    bindings: list[BindingOut]


class ProjectAgentOut(AgentOut):
    can_use: bool


class AdminAgentOut(AgentOut):
    current_run: dict | None = None
