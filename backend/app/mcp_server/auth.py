"""Bearer authentication for the MCP endpoint, as a pure ASGI middleware."""

import contextvars
import uuid

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.models import TokenScope
from app.auth.tokens import resolve_bearer
from app.core.db import SessionLocal

current_mcp_user_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "current_mcp_user_id", default=None
)


class McpBearerAuth:
    """Resolves `Authorization: Bearer <mcp-scope token>`; anything else is 401 invalid_token."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        scheme, _, raw = Headers(scope=scope).get("authorization", "").partition(" ")
        user_id = None
        if scheme.lower() == "bearer" and raw.strip():
            async with SessionLocal() as db:
                resolved = await resolve_bearer(db, raw.strip(), scope=TokenScope.mcp)
                if resolved is not None:
                    user_id = resolved[0].id
                    await db.commit()  # last_used_at
        if user_id is None:
            response = JSONResponse(
                {"detail": "invalid_token"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
            await response(scope, receive, send)
            return
        reset = current_mcp_user_id.set(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_mcp_user_id.reset(reset)
