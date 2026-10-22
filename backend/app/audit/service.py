import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog


async def record(
    session: AsyncSession,
    action: str,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    data: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            action=action,
            actor_user_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            data=data or {},
        )
    )
