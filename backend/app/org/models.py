from sqlalchemy import String, false, true
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
    # ADM-1: the nightly dream (hour in UTC; null: the MEMORY_DREAM_HOUR_UTC setting)
    dream_enabled: Mapped[bool] = mapped_column(default=True, server_default=true())
    dream_hour_utc: Mapped[int | None]
    # ADM-1: what a new project starts with
    default_finishing_option: Mapped[str] = mapped_column(String(20), default="pull_request",
                                                          server_default="pull_request")
    default_require_human_code_review: Mapped[bool] = mapped_column(default=False, server_default=false())
    default_sprints_enabled: Mapped[bool] = mapped_column(default=True, server_default=true())
    default_commit_docs_to_repo: Mapped[bool] = mapped_column(default=False, server_default=false())
