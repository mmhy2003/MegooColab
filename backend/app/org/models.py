from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

ORG_SETTINGS_ID = 1


class OrgSettings(TimestampMixin, Base):
    __tablename__ = "org_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=ORG_SETTINGS_ID, autoincrement=False)
    name: Mapped[str] = mapped_column(String(200))
    smtp_host: Mapped[str | None]
    smtp_port: Mapped[int | None]
    smtp_user: Mapped[str | None]
    smtp_password_enc: Mapped[str | None]
    smtp_from: Mapped[str | None]
    smtp_tls: Mapped[bool] = mapped_column(default=True)
