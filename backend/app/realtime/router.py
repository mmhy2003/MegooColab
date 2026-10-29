import asyncio
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.deps import user_from_session_token
from app.auth.models import Role
from app.auth.service import SESSION_COOKIE
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.events import Event, hub
from app.projects.access import accessible_project_ids
from app.ratelimit.ws import CLOSE_RATE_LIMITED, connect_allowed
from app.teams.service import user_team_ids

router = APIRouter()

# also the re-authorization interval: a socket never outlives its session by more than this
PING_EVERY_SECONDS = 25
CLOSE_UNAUTHORIZED = 4401
CLOSE_FOREIGN_ORIGIN = 4403
RECHECK_EVENTS = {"membership.changed", "sessions.revoked"}


Access = tuple[uuid.UUID, set[uuid.UUID] | None, set[uuid.UUID] | None]


async def _authorize(token: str | None) -> Access | None:
    """(user id, visible project ids, team ids — None means all) for a live session, else None."""
    async with SessionLocal() as db:
        user = await user_from_session_token(db, token)
        if user is None:
            return None
        teams = None if user.role == Role.admin else await user_team_ids(db, user.id)
        return user.id, await accessible_project_ids(db, user), teams


def _visible(
    event: Event, user_id: uuid.UUID, allowed: set[uuid.UUID] | None, teams: set[uuid.UUID] | None
) -> bool:
    if event.team_id is not None:
        return teams is None or event.team_id in teams
    if event.user_id is not None and event.project_id is None:
        return event.user_id == user_id
    if event.project_id is None:
        # org Knowledge Base space: everyone
        return event.space_id is not None
    return allowed is None or event.project_id in allowed


def same_site(websocket: WebSocket) -> bool:
    """A browser names the page that opens a socket (Origin): it must be this site, as the request reached it or as
    PUBLIC_URL names it, so another site's page can't listen with the visitor's cookie. No Origin: not a browser."""
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    host = urlsplit(origin).netloc.lower()
    return host in {websocket.headers.get("host", "").lower(), urlsplit(get_settings().public_url).netloc.lower()}


@router.websocket("/api/ws")
async def events_socket(websocket: WebSocket) -> None:
    if not same_site(websocket):
        await websocket.close(code=CLOSE_FOREIGN_ORIGIN)
        return
    if not await connect_allowed(websocket):
        await websocket.close(code=CLOSE_RATE_LIMITED)
        return
    # subscribe before authorizing so nothing published after the handshake is missed
    queue = hub.subscribe()
    token = websocket.cookies.get(SESSION_COOKIE)
    try:
        auth = await _authorize(token)
        await websocket.accept()
        if auth is None:
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return
        user_id, allowed, teams = auth
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
                _, allowed, teams = auth
            if event is None:
                await websocket.send_json({"type": "ping"})
            elif event.type != "sessions.revoked" and _visible(event, user_id, allowed, teams):
                await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(queue)
