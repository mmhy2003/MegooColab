import uuid

from fastapi import APIRouter, status

from app.auth.deps import AuthedUser
from app.chats import service
from app.chats.schemas import BoardDefaults, BoardIn, ChatIn, ChatOut, MessageIn, MessageOut, RoundOut
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


@router.post("/api/chats/{chat_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_message(chat_id: uuid.UUID, body: MessageIn, user: AuthedUser, db: DbSession) -> MessageOut:
    """Answers the agent's question, asks for changes to the design or plan waiting, tells the working agent,
    starts it again, or starts the next round: whatever the chat waits for when the message arrives."""
    from app.projects.models import Project
    from app.workflow import engine
    from app.workflow.instructions import steer_after_commit

    chat = await service.get_chat_for(db, user, chat_id)
    what, task, steer = await service.send_message(db, user, chat, body.body)
    key = f"{(await db.get(Project, task.project_id)).key}-{task.number}"
    await db.commit()
    if steer is not None:
        await steer_after_commit(steer)
    await engine.dispatch_queued(db)
    return MessageOut(intent=what, round_key=key)


@router.post("/api/chats/{chat_id}/end")
async def end_chat(chat_id: uuid.UUID, user: AuthedUser, db: DbSession) -> ChatOut:
    chat = await service.end_chat(db, user, await service.get_chat_for(db, user, chat_id))
    return await service.chat_out(db, chat, user)


@router.get("/api/chats/{chat_id}/rounds/{n}/board")
async def board_defaults(chat_id: uuid.UUID, n: int, user: AuthedUser, db: DbSession) -> BoardDefaults:
    return await service.board_defaults(db, await service.get_chat_for(db, user, chat_id), n)


@router.post("/api/chats/{chat_id}/rounds/{n}/board")
async def decide_board(chat_id: uuid.UUID, n: int, body: BoardIn, user: AuthedUser, db: DbSession) -> RoundOut:
    """Add this to the board? The round becomes an ordinary task (its steps as subtasks), or stays a chat."""
    chat = await service.get_chat_for(db, user, chat_id)
    task = await service.decide_board(db, user, chat, n, body)
    return await service.round_out(db, chat, task)
