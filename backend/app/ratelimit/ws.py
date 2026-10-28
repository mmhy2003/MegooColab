"""The WebSocket connect limit (live updates and runners): counted before the handshake is accepted."""

from fastapi import WebSocket
from starlette.requests import cookie_parser

from app.ratelimit import limits, store
from app.ratelimit.clientip import client_ip
from app.ratelimit.middleware import credential_subject

# closing before accept refuses the handshake; 1008 = policy violation
CLOSE_RATE_LIMITED = 1008


async def connect_allowed(websocket: WebSocket) -> bool:
    ip = client_ip(websocket)
    subject = credential_subject(websocket.headers, cookie_parser(websocket.headers.get("cookie", ""))) or f"ip:{ip}"
    limit = limits.get("ws_connect")
    try:
        await store.raise_if_blocked(await store.hit(limit, subject), limit, ip=ip, subject=subject)
    except store.RateLimited:
        return False
    return True
