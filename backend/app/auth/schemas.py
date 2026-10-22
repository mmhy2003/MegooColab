import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, StringConstraints

from app.auth.models import Role, UserStatus

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
