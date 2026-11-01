import uuid
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

from app.core.text import NoNulStr

System = Literal["windows", "linux", "macos"]


class Entry(BaseModel):
    """A header (web address MCP) or an environment variable (command MCP)."""

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,99}$")
    value: str = Field(default="", max_length=2000)
    secret: bool = False


class Command(BaseModel):
    command: NoNulStr = Field(min_length=1, max_length=500)
    args: list[Annotated[str, Field(max_length=2000)]] = Field(default=[], max_length=50)


class McpSpec(BaseModel):
    """An MCP server's setup in the hub's neutral form. Secret values are never kept here."""

    transport: Literal["http", "stdio"]
    url: str | None = Field(default=None, max_length=2000)
    headers: list[Entry] = Field(default=[], max_length=50)
    command: Command | None = None
    os_commands: dict[System, Command] = {}
    env: list[Entry] = Field(default=[], max_length=50)
    # locations (rules.flagged_values) the owner confirmed are not secrets
    acknowledged: list[Annotated[str, Field(max_length=200)]] = Field(default=[], max_length=100)

    @model_validator(mode="after")
    def _check(self) -> "McpSpec":
        from app.hub.rules import placeholders, secret_slots

        if self.transport == "http":
            if not self.url or urlparse(self.url).scheme not in ("http", "https") or not urlparse(self.url).netloc:
                raise ValueError("an http MCP needs an http(s) url")
        elif self.command is None and not self.os_commands:
            raise ValueError("a stdio MCP needs a command")
        for entries in (self.headers, self.env):
            names = [e.name for e in entries]
            if len(names) != len(set(names)):
                raise ValueError("duplicate names")
        slots = set(secret_slots(self))
        texts = [self.url or ""]
        for c in [self.command, *self.os_commands.values()]:
            if c is not None:
                texts += c.args
        if any(p not in slots for t in texts for p in placeholders(t)):
            raise ValueError("hub_unknown_placeholder")
        return self


class ToolIn(BaseModel):
    kind: Literal["mcp"]
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    description: NoNulStr = Field(default="", max_length=2000)
    spec: McpSpec
    read_only_safe: bool = False


class ToolPatch(BaseModel):
    name: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    description: NoNulStr | None = Field(default=None, max_length=2000)
    spec: McpSpec | None = None
    read_only_safe: bool | None = None


class SecretsIn(BaseModel):
    values: dict[str, Annotated[str, Field(max_length=4000)]] = Field(max_length=100)


class SecretSlot(BaseModel):
    name: str
    set: bool


class Named(BaseModel):
    id: uuid.UUID
    name: str


class Sharing(BaseModel):
    teams: list[Named] = []
    users: list[Named] = []
    everyone: bool = False


class ToolSummary(BaseModel):
    id: uuid.UUID
    kind: Literal["mcp", "skill"]
    name: str
    description: str
    version: int
    rev: int
    owner: Named
    is_copy: bool
    source_state: Literal["ok", "update_available", "no_longer_shared"] | None = None
    removed: bool
    secrets_missing: bool  # owner only, else false
    runs_code: bool
    read_only_safe: bool
    sharing: Sharing | None = None  # owner only


class ToolFileOut(BaseModel):
    path: str
    size: int
    runs_on: list[str] | None = None


class ToolSource(BaseModel):
    id: uuid.UUID
    name: str
    owner_name: str
    version: int


class ToolOut(ToolSummary):
    spec: McpSpec | None = None
    secrets: list[SecretSlot] = []
    files: list[ToolFileOut] | None = None
    source: ToolSource | None = None
    flagged: list[str] = []
    can_edit: bool
