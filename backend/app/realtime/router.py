import asyncio
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.deps import user_from_session_token
from app.auth.models import User
from app.auth.service import SESSION_COOKIE
from app.core.db import SessionLocal
from app.core.events import Event, hub
from app.projects.access import accessible_project_ids

router = APIRouter()

PING_EVERY_SECONDS = 25
CLOSE_UNAUTHORIZED = 4401


async def _authenticate(token: str | None) -> User | None:
    async with SessionLocal() as db:
        return await user_from_session_token(db, token)


async def _allowed_projects(user_id: uuid.UUID) -> tuple[User | None, set[uuid.UUID] | None]:
    """Re-reads the user (role/status may have changed) and the projects they can see."""
    async with SessionLocal() as db:
        from app.auth.models import UserStatus

        user = await db.get(User, user_id)
        if user is None or user.status != UserStatus.active:
            return None, set()
        return user, await accessible_project_ids(db, user)


def _visible(event: Event, user_id: uuid.UUID, allowed: set[uuid.UUID] | None) -> bool:
    if event.user_id is not None and event.project_id is None:
        return event.user_id == user_id
    if event.project_id is None:
        return False
    return allowed is None or event.project_id in allowed


@router.websocket("/api/ws")
async def events_socket(websocket: WebSocket) -> None:
    # subscribe before accepting so nothing published after the handshake is missed
    queue = hub.subscribe()
    try:
        user = await _authenticate(websocket.cookies.get(SESSION_COOKIE))
        await websocket.accept()
        if user is None:
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return
        user_id = user.id
        _, allowed = await _allowed_projects(user_id)
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=PING_EVERY_SECONDS)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            if event.type == "user.deactivated" and event.user_id == user_id:
                await websocket.close(code=CLOSE_UNAUTHORIZED)
                return
            if (event.type == "membership.changed" and event.user_id == user_id) or event.type == "project.updated":
                current, allowed = await _allowed_projects(user_id)
                if current is None:
                    await websocket.close(code=CLOSE_UNAUTHORIZED)
                    return
            if _visible(event, user_id, allowed):
                await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(queue)
