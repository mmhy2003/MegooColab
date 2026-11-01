import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
    last_failed_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(IdMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TokenPurpose(StrEnum):
    invite = "invite"
    reset = "reset"


class OneTimeToken(IdMixin, Base):
    __tablename__ = "one_time_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[TokenPurpose] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TokenScope(StrEnum):
    mcp = "mcp"
    runner = "runner"


class PersonalAccessToken(IdMixin, Base):
    __tablename__ = "personal_access_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(8))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # a runner token's machine: its system as its last hello said ("windows" | "linux" | "macos" | other)
    runner_os: Mapped[str | None] = mapped_column(String(10))


class ChallengePurpose(StrEnum):
    register = "register"
    login = "login"
    remove = "remove"


class Passkey(IdMixin, Base):
    """A WebAuthn credential: a second sign-in factor, alternative to the authenticator code."""

    __tablename__ = "passkeys"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(default=0)
    transports: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    aaguid: Mapped[str | None] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebauthnChallenge(IdMixin, Base):
    """The one open WebAuthn challenge per person and purpose: single use, valid a few minutes. In Postgres, not
    Valkey, which is optional."""

    __tablename__ = "webauthn_challenges"
    __table_args__ = (UniqueConstraint("user_id", "purpose", name="uq_webauthn_challenges_user_purpose"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[ChallengePurpose] = mapped_column(String(20))
    challenge: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
