import uuid

from fastapi import APIRouter, status

from app.auth.deps import AuthedUser
from app.chats import service
from app.chats.schemas import ChatIn, ChatOut
from app.core.db import DbSession

router = APIRouter(tags=["chats"])


@router.post("/api/chats", status_code=status.HTTP_201_CREATED)
async def start_chat(body: ChatIn, user: AuthedUser, db: DbSession) -> ChatOut:
    from app.workflow import engine  # local: the engine imports the task modules

    chat = await service.start_chat(db, user, body)
    out = await service.chat_out(db, chat, user)
    await engine.dispatch_queued(db)
    return out


@router.get("/api/chats")
async def list_chats(user: AuthedUser, db: DbSession, project: str | None = None) -> list[ChatOut]:
    return await service.chats_out(db, await service.visible_chats(db, user, project), user)


@router.get("/api/chats/{chat_id}")
async def get_chat(chat_id: uuid.UUID, user: AuthedUser, db: DbSession) -> ChatOut:
    return await service.chat_out(db, await service.get_chat_for(db, user, chat_id), user)
