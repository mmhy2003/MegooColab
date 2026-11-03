import uuid
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.text import NoNulStr
from app.git.models import GitKind


def clean_base_url(value: str) -> str:
    """http(s)://host[:port][/prefix], no credentials, query or fragment, no trailing slash."""
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("invalid_base_url")
    if parts.query or parts.fragment or len(value) > 300:
        raise ValueError("invalid_base_url")
    return value


class GitConnectionIn(BaseModel):
    name: NoNulStr = Field(min_length=1, max_length=100)
    kind: GitKind
    # absent: the kind's hosted service (GitHub.com, GitLab.com); a self-hosted server, and every Gitea, gives its own.
    # No webhook secret: each repository has its own.
    base_url: NoNulStr | None = Field(default=None, min_length=1, max_length=300)
    token: NoNulStr = Field(min_length=1, max_length=500)

    @field_validator("base_url")
    @classmethod
    def _base(cls, v: str | None) -> str | None:
        return clean_base_url(v) if v is not None else None

    @model_validator(mode="after")
    def _hosted(self) -> "GitConnectionIn":
        if self.base_url is None and self.kind == GitKind.gitea:
            raise ValueError("base_url_required")
        return self


class GitConnectionPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=100)
    base_url: NoNulStr | None = Field(default=None, min_length=1, max_length=300)
    # absent: keep; a value: replace (the token cannot be removed, only replaced)
    token: NoNulStr | None = Field(default=None, min_length=1, max_length=500)
    # absent: keep; "": no webhooks; a value: replace
    webhook_secret: NoNulStr | None = Field(default=None, max_length=200)

    @field_validator("base_url")
    @classmethod
    def _base(cls, v: str | None) -> str | None:
        return clean_base_url(v) if v is not None else None


class WaitingRepo(BaseModel):
    project_key: str
    name: str


class GitConnectionOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: GitKind
    base_url: str
    hosted: bool = False
    token_set: bool
    # the shared secret from before repositories had their own (still accepted at the connection's old address)
    webhook_secret_set: bool
    # while it is set: the connection's repositories whose own webhook has received nothing yet
    waiting_repositories: list[WaitingRepo] = []


class GitConnectionTest(BaseModel):
    ok: bool
    login: str | None = None
    error: str | None = None


class ConnectionRef(BaseModel):
    id: uuid.UUID
    name: str
