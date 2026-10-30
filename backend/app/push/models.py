import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class PushSubscription(IdMixin, Base):
    """One device (a browser or an installed app) that gets this person's push notifications."""

    __tablename__ = "push_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)  # the browser's push service address
    p256dh: Mapped[str] = mapped_column(String(200))  # the browser's keys for encrypting the message
    auth: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))  # e.g. "Chrome on Windows", from the user agent
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
