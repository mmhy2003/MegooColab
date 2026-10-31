import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.auth.models import Role
from app.auth.schemas import LowerEmail, Password, UserOut


class InviteIn(BaseModel):
    email: LowerEmail
    name: str = Field(min_length=1, max_length=200)
    role: Role


class InviteOut(BaseModel):
    user: UserOut
    invite_url: str
    email_sent: bool


class CreateUserIn(BaseModel):
    email: LowerEmail
    name: str = Field(min_length=1, max_length=200)
    role: Role
    temporary_password: Password


class ResetLinkOut(BaseModel):
    reset_url: str


class UpdateUserIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None


class AdminUserDetailsOut(BaseModel):
    """What only admins see of a person, beside the shared UserOut."""

    user_id: uuid.UUID
    totp: bool
    passkeys: int
    last_login_at: datetime | None
