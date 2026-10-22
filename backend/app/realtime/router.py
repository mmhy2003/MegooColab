import asyncio
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.deps import user_from_session_token
from app.auth.service import SESSION_COOKIE
from app.core.db import SessionLocal
from app.core.events import Event, hub
from app.projects.access import accessible_project_ids

router = APIRouter()

# also the re-authorization interval: a socket never outlives its session by more than this
PING_EVERY_SECONDS = 25
CLOSE_UNAUTHORIZED = 4401
RECHECK_EVENTS = {"membership.changed", "sessions.revoked"}


async def _authorize(token: str | None) -> tuple[uuid.UUID, set[uuid.UUID] | None] | None:
    """(user id, visible project ids — None means all) for a live session, else None."""
    async with SessionLocal() as db:
        user = await user_from_session_token(db, token)
        if user is None:
            return None
        return user.id, await accessible_project_ids(db, user)


def _visible(event: Event, user_id: uuid.UUID, allowed: set[uuid.UUID] | None) -> bool:
    if event.user_id is not None and event.project_id is None:
        return event.user_id == user_id
    if event.project_id is None:
        return False
    return allowed is None or event.project_id in allowed


@router.websocket("/api/ws")
async def events_socket(websocket: WebSocket) -> None:
    # subscribe before authorizing so nothing published after the handshake is missed
    queue = hub.subscribe()
    token = websocket.cookies.get(SESSION_COOKIE)
    try:
        auth = await _authorize(token)
        await websocket.accept()
        if auth is None:
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return
        user_id, allowed = auth
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=PING_EVERY_SECONDS)
            except TimeoutError:
                event = None
            mine = event is not None and event.user_id == user_id
            if event is None or event.type == "project.updated" or (mine and event.type in RECHECK_EVENTS) or (
                mine and event.type == "user.deactivated"
            ):
                # re-authorize: session still valid, user still active, access recomputed
                auth = await _authorize(token)
                if auth is None:
                    await websocket.close(code=CLOSE_UNAUTHORIZED)
                    return
                _, allowed = auth
            if event is None:
                await websocket.send_json({"type": "ping"})
            elif event.type != "sessions.revoked" and _visible(event, user_id, allowed):
                await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(queue)
