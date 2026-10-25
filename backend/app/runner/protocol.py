"""Runner <-> server wire protocol: JSON text frames, each `{"type": ..., ...}`.

The Go runner (Task 11) mirrors these shapes exactly.
"""

import posixpath
import re
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from app.core.text import NoNulStr

CLOSE_UNAUTHORIZED = 4401  # missing, invalid or revoked token / deactivated user
CLOSE_REPLACED = 4409  # a newer connection for the same user took over
CLOSE_PROTOCOL_ERROR = 4400
CLOSE_IDLE = 4408  # nothing received for IDLE_TIMEOUT_SECONDS


class _FromRunner(BaseModel):
    model_config = ConfigDict(extra="forbid")


Problems = Annotated[list[Annotated[NoNulStr, Field(max_length=200)]], Field(max_length=10)]


class AgentReport(_FromRunner):
    agent_id: uuid.UUID
    available: bool
    problems: Problems = []


class Hello(_FromRunner):
    type: Literal["hello"]
    runner_version: NoNulStr = Field(max_length=100)
    os: NoNulStr = Field(max_length=100)
    arch: NoNulStr = Field(max_length=100)
    agents: list[AgentReport] = []
    capabilities: list[Annotated[NoNulStr, Field(max_length=50)]] = Field(default=[], max_length=50)


class Heartbeat(_FromRunner):
    type: Literal["heartbeat"]


class AgentStatus(_FromRunner):
    type: Literal["agent_status"]
    agent_id: uuid.UUID
    available: bool
    problems: Problems = []


class RunUpdate(_FromRunner):
    type: Literal["run_update"]
    run_id: uuid.UUID
    seq: int
    kind: NoNulStr = Field(max_length=40)
    data: dict[str, Any]


class GitState(_FromRunner):
    head: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    branch: NoNulStr | None = Field(default=None, max_length=200)
    dirty: bool


class RunFinished(_FromRunner):
    type: Literal["run_finished"]
    run_id: uuid.UUID
    outcome: Literal["completed", "failed", "cancelled"]
    summary: NoNulStr = Field(max_length=2000)
    error: NoNulStr | None = Field(default=None, max_length=10000)
    session_id: NoNulStr | None = Field(default=None, max_length=200)
    git_before: GitState | None = None
    git_after: GitState | None = None


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


MAX_FILES_BYTES = 2 * 1024 * 1024
FILES_PREFIX = ".megoocolab/"
REPO_FILES_PREFIX = "docs/superpowers/"


_COMPONENT = re.compile(r"[A-Za-z0-9._-]+")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _safe_component(c: str) -> bool:
    """No dot-segments, no trailing dot, no Windows device names (with or without an extension)."""
    return c not in (".", "..") and not c.endswith(".") and c.split(".")[0].upper() not in _RESERVED


def check_relative_path(path: str, prefix: str) -> str:
    """A normalised relative path strictly below `prefix`; ValueError otherwise."""
    if (
        "\\" in path
        or "\x00" in path
        or path.startswith("/")
        or not path.startswith(prefix)
        or len(path) == len(prefix)
        or posixpath.normpath(path) != path
        or not all(_COMPONENT.fullmatch(c) and _safe_component(c) for c in path.split("/"))
    ):
        raise ValueError(f"path not allowed: {path!r}")
    return path


class RunFile(BaseModel):
    path: str
    content: str


class McpAccess(BaseModel):
    url: str
    token: str


class RunStart(BaseModel):
    type: Literal["run_start"] = "run_start"
    run_id: uuid.UUID
    agent_id: uuid.UUID
    task: RunTask
    local_path: str
    policy: Literal["read_only", "workspace"]
    prompt: str
    # protocol v2: only sent for workflow runs
    role: str | None = None
    stage: str | None = None
    step: int | None = None
    resume_session_id: str | None = None
    resume_prompt: str | None = None
    mcp: McpAccess | None = None
    files: list[RunFile] = []
    repo_files: list[RunFile] = []
    commit_message: str | None = None

    @field_validator("files")
    @classmethod
    def _files_ok(cls, files: list[RunFile]) -> list[RunFile]:
        for f in files:
            check_relative_path(f.path, FILES_PREFIX)
        if sum(len(f.content.encode()) for f in files) > MAX_FILES_BYTES:
            raise ValueError("files exceed 1 MB")
        return files

    @field_validator("repo_files")
    @classmethod
    def _repo_files_ok(cls, files: list[RunFile]) -> list[RunFile]:
        for f in files:
            check_relative_path(f.path, REPO_FILES_PREFIX)
        return files


_V1_START_FIELDS = {"type", "run_id", "agent_id", "task", "local_path", "policy", "prompt"}
# derived, so a future RunStart field cannot leak to a v1 runner
V2_START_FIELDS = set(RunStart.model_fields) - _V1_START_FIELDS


class RunCancel(BaseModel):
    type: Literal["run_cancel"] = "run_cancel"
    run_id: uuid.UUID


class ConfigChanged(BaseModel):
    type: Literal["config_changed"] = "config_changed"


ServerMessage = Welcome | RunStart | RunCancel | ConfigChanged
