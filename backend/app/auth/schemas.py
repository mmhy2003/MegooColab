import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, StringConstraints

from app.auth.models import Role, UserStatus
from app.core.text import NoNulStr

PASSWORD_MIN_LENGTH = 10

Password = Annotated[str, StringConstraints(min_length=PASSWORD_MIN_LENGTH, max_length=200)]
LowerEmail = Annotated[EmailStr, AfterValidator(str.lower)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: Role
    status: UserStatus
    must_change_password: bool
    totp_enabled: bool


class UserEnvelope(BaseModel):
    user: UserOut


class PasskeyOut(BaseModel):
    """A passkey as its owner sees it: never any key material."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


PasskeyName = Annotated[NoNulStr, AfterValidator(str.strip), StringConstraints(min_length=1, max_length=100)]


class PasskeyCreateIn(BaseModel):
    name: PasskeyName
    credential: dict


class PasskeyRemoveIn(BaseModel):
    password: str
    passkey: dict | None = None
    totp_code: str | None = None
