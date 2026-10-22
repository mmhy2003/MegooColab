import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class Event(BaseModel):
    type: str
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


async def publish(db: AsyncSession, event: Event) -> None:
    # no-op until Task 14 wires up the realtime hub
    return None
