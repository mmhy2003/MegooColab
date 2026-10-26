import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.core.text import NoNulStr


class ProviderIn(BaseModel):
    name: NoNulStr = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_\-]+$")
    api_key: NoNulStr | None = Field(default=None, max_length=2000)
    api_base: NoNulStr | None = Field(default=None, max_length=500)


class ProviderPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, min_length=1, max_length=100)
    kind: str | None = Field(default=None, min_length=1, max_length=50, pattern=r"^[a-z0-9_\-]+$")
    # absent: keep the stored key; "": remove it; anything else: replace it
    api_key: NoNulStr | None = Field(default=None, max_length=2000)
    api_base: NoNulStr | None = Field(default=None, max_length=500)


class ProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    api_base: str | None
    has_key: bool


class JobModelIn(BaseModel):
    provider_id: uuid.UUID | None
    model: NoNulStr = Field(default="", max_length=200)


class JobModelOut(BaseModel):
    job: str
    provider_id: uuid.UUID | None
    model: str


class TestResult(BaseModel):
    ok: bool
    model: str | None
    error: str | None


class UsageRow(BaseModel):
    day: date
    job: str
    model: str
    calls: int
    failures: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
