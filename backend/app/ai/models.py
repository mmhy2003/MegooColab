import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin


class AiProvider(IdMixin, Base):
    __tablename__ = "ai_providers"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    # LiteLLM provider prefix: "openai", "azure", "ollama", ...
    kind: Mapped[str] = mapped_column(String(50))
    api_key_enc: Mapped[str | None] = mapped_column(Text)
    api_base: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiJobModel(Base):
    __tablename__ = "ai_job_models"

    job: Mapped[str] = mapped_column(String(50), primary_key=True)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_providers.id", ondelete="SET NULL"))
    model: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AiUsage(IdMixin, Base):
    __tablename__ = "ai_usage"

    job: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(300))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(14, 6, asdecimal=False))
    ok: Mapped[bool]
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
