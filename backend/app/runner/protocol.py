"""Runner <-> server wire protocol: JSON text frames, each `{"type": ..., ...}`.

The Go runner (Task 11) mirrors these shapes exactly.
"""

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

CLOSE_UNAUTHORIZED = 4401  # missing, invalid or revoked token / deactivated user
CLOSE_REPLACED = 4409  # a newer connection for the same user took over
CLOSE_PROTOCOL_ERROR = 4400
CLOSE_IDLE = 4408  # nothing received for IDLE_TIMEOUT_SECONDS


class _FromRunner(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentReport(_FromRunner):
    agent_id: uuid.UUID
    available: bool
    problems: list[str] = []


class Hello(_FromRunner):
    type: Literal["hello"]
    runner_version: str
    os: str
    arch: str
    agents: list[AgentReport] = []


class Heartbeat(_FromRunner):
    type: Literal["heartbeat"]


class AgentStatus(_FromRunner):
    type: Literal["agent_status"]
    agent_id: uuid.UUID
    available: bool
    problems: list[str] = []


class RunUpdate(_FromRunner):
    type: Literal["run_update"]
    run_id: uuid.UUID
    seq: int
    kind: str
    data: dict[str, Any]


class RunFinished(_FromRunner):
    type: Literal["run_finished"]
    run_id: uuid.UUID
    outcome: Literal["completed", "failed", "cancelled"]
    summary: str = Field(max_length=2000)
    error: str | None = None


RunnerMessage = Annotated[
    Hello | Heartbeat | AgentStatus | RunUpdate | RunFinished, Field(discriminator="type")
]
runner_message = TypeAdapter(RunnerMessage)


class WelcomeBinding(BaseModel):
    project_key: str
    local_path: str


class WelcomeAgent(BaseModel):
    agent_id: uuid.UUID
    name: str
    program: str
    max_concurrent_runs: int
    bindings: list[WelcomeBinding]


class Welcome(BaseModel):
    type: Literal["welcome"] = "welcome"
    user_id: uuid.UUID
    agents: list[WelcomeAgent]


class RunTask(BaseModel):
    key: str
    title: str
    description_md: str
    project_key: str


class RunStart(BaseModel):
    type: Literal["run_start"] = "run_start"
    run_id: uuid.UUID
    agent_id: uuid.UUID
    task: RunTask
    local_path: str
    policy: Literal["read_only", "workspace"]
    prompt: str


class RunCancel(BaseModel):
    type: Literal["run_cancel"] = "run_cancel"
    run_id: uuid.UUID


class ConfigChanged(BaseModel):
    type: Literal["config_changed"] = "config_changed"


ServerMessage = Welcome | RunStart | RunCancel | ConfigChanged
