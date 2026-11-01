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
