import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.text import NoNulStr
from app.kb.schemas import Named

NAME_MAX = 100
DESCRIPTION_MAX = 1000
VALUE_MAX = 32_768


class SecretIn(BaseModel):
    # the name's rules are checked by the service (422 secret_name_invalid / secret_name_reserved)
    name: NoNulStr = Field(max_length=NAME_MAX)
    description: NoNulStr = Field(min_length=1, max_length=DESCRIPTION_MAX)
    value: NoNulStr = Field(min_length=1, max_length=VALUE_MAX)


class SecretPatch(BaseModel):
    name: NoNulStr | None = Field(default=None, max_length=NAME_MAX)
    description: NoNulStr | None = Field(default=None, min_length=1, max_length=DESCRIPTION_MAX)


class SecretValueIn(BaseModel):
    value: NoNulStr = Field(min_length=1, max_length=VALUE_MAX)


class SecretOut(BaseModel):
    """A secret as anyone sees it: never its value."""

    id: uuid.UUID
    name: str
    description: str
    updated_at: datetime
    value_updated_at: datetime
    updated_by: Named | None


class OutdatedAgent(BaseModel):
    id: uuid.UUID
    name: str
