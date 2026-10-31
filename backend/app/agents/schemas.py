import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from app.agents.models import AgentProgram, AnswerMode
from app.auth.schemas import UserOut
from app.core.text import NoNulStr

MaxRuns = Annotated[int, Field(ge=1, le=3)]
# a model name or alias ("opus", "gpt-5-codex"); blank is no choice: the program's own default
ModelName = Annotated[NoNulStr, Field(max_length=100), AfterValidator(lambda v: v.strip() or None)]


class AgentIn(BaseModel):
    program: AgentProgram
    name: NoNulStr | None = Field(default=None, max_length=200)
    answer_mode: AnswerMode = AnswerMode.manual
    max_concurrent_runs: MaxRuns = 1
    runner_token_id: uuid.UUID | None = None
    model: ModelName | None = None


class AgentPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=200)
    answer_mode: AnswerMode | None = None
    max_concurrent_runs: MaxRuns | None = None
    runner_token_id: uuid.UUID | None = None  # only when sent: null unlinks
    model: ModelName | None = None  # only when sent: null or blank goes back to the program's default


class BindingIn(BaseModel):
    project_ref: NoNulStr = Field(min_length=1, max_length=64)
    local_path: NoNulStr = Field(max_length=1000)


class BindingsIn(BaseModel):
    bindings: list[BindingIn]


class BindingOut(BaseModel):
    project_id: uuid.UUID
    project_key: str
    local_path: str | None


class RunnerInfo(BaseModel):
    """The owner's live runner, as its hello said (the frontend compares the version with the latest release)."""

    version: str
    os: str


class MachineOut(BaseModel):
    """The runner token an agent is linked to (shown to its owner and admins)."""

    token_id: uuid.UUID
    name: str
    expired: bool


class ModelOption(BaseModel):
    """A model the agent's program offered, as its runner reported it."""

    value: str
    name: str


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
    runner: RunnerInfo | None = None  # None while the owner's runner is offline
    machine: MachineOut | None = None  # owner and admins only; None when unlinked
    model: str | None = None  # None: the program's own default
    known_models: list[ModelOption] = []  # owner only


class ProjectAgentOut(AgentOut):
    can_use: bool


class AdminAgentOut(AgentOut):
    current_run: dict | None = None
