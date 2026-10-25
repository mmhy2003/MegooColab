"""Bearer authentication for the MCP endpoint (a pure ASGI middleware), the per-tool session, and the scope of
run tokens.

A run token (`mgr_`, AGT-33) authenticates as the agent's owner, but only for its run's task (wrong_task) and
role (not_allowed_in_role); tools that act across tasks refuse it outright."""

import contextlib
import contextvars
import uuid
from collections.abc import AsyncIterator

from fastapi import HTTPException
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.agent_runs.models import AgentRun
from app.agent_runs.tokens import RUN_TOKEN_PREFIX, resolve_run_token
from app.auth.deps import require_password_ok
from app.auth.models import TokenScope, User, UserStatus
from app.auth.tokens import resolve_bearer
from app.core.db import SessionLocal
from app.projects.models import Project
from app.tasks.models import Task

current_mcp_user_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "current_mcp_user_id", default=None
)
# the run behind a `mgr_` run token; None for a personal `mgc_` token
current_run: contextvars.ContextVar[AgentRun | None] = contextvars.ContextVar("current_run", default=None)


@contextlib.asynccontextmanager
async def tool_session() -> AsyncIterator[tuple[AsyncSession, User]]:
    """A DB session plus the token owner. Commits on success; REST errors become tool errors with their code."""
    user_id = current_mcp_user_id.get()
    if user_id is None:
        raise ToolError("invalid_token")
    async with SessionLocal() as db:
        try:
            user = await db.get(User, user_id)
            if user is None or user.status != UserStatus.active:
                raise ToolError("invalid_token")
            await require_password_ok(user)
            yield db, user
            await db.commit()
        except HTTPException as e:
            await db.rollback()
            raise ToolError(str(e.detail)) from None
        except BaseException:
            await db.rollback()
            raise


def refuse_run_token() -> None:
    """For tools that reach beyond one task (listing, creating, editing, moving): never with a run token."""
    if current_run.get() is not None:
        raise ToolError("not_allowed_in_role")


async def require_run_task(db: AsyncSession, key: str) -> None:
    """With a run token, `key` must name the run's own task (wrong_task). Checked before the key is looked up,
    so a run token never touches, or learns anything about, another task."""
    run = current_run.get()
    if run is None:
        return
    task = await db.get(Task, run.task_id)
    project = await db.get(Project, task.project_id) if task is not None else None
    if project is None or not isinstance(key, str) or key.strip().upper() != f"{project.key}-{task.number}".upper():
        raise ToolError("wrong_task")


class McpBearerAuth:
    """Resolves `Authorization: Bearer <mcp-scope token or run token>`; anything else is 401 invalid_token."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        scheme, _, raw = Headers(scope=scope).get("authorization", "").partition(" ")
        user_id = None
        run = None
        raw = raw.strip()
        if scheme.lower() == "bearer" and raw:
            async with SessionLocal() as db:
                if raw.startswith(RUN_TOKEN_PREFIX):
                    resolved_run = await resolve_run_token(db, raw)
                    if resolved_run is not None:
                        user_id, run = resolved_run[0].id, resolved_run[1]
                        db.expunge(run)
                else:
                    resolved = await resolve_bearer(db, raw, scope=TokenScope.mcp)
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
        reset_run = current_run.set(run)
        try:
            await self.app(scope, receive, send)
        finally:
            current_run.reset(reset_run)
            current_mcp_user_id.reset(reset)
