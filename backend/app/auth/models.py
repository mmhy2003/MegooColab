from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Role(StrEnum):
    admin = "admin"
    manager = "manager"
    member = "member"
    viewer = "viewer"


class UserStatus(StrEnum):
    invited = "invited"
    active = "active"
    deactivated = "deactivated"


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(String(20))
    status: Mapped[UserStatus] = mapped_column(String(20))
    password_hash: Mapped[str | None]
    must_change_password: Mapped[bool] = mapped_column(default=False)
    totp_secret_enc: Mapped[str | None]
    totp_enabled: Mapped[bool] = mapped_column(default=False)
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
