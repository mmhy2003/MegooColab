"""Bearer authentication for the MCP endpoint (a pure ASGI middleware), the per-tool session, and the scope of
run tokens.

A run token (`mgr_`, AGT-33) authenticates as the agent's owner, but only for its run's task (wrong_task) and
role (not_allowed_in_role); tools that act across tasks refuse it outright."""

import contextlib
import json
import contextvars
import uuid
from collections.abc import AsyncIterator

from fastapi import HTTPException, status
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.agent_runs.models import AgentRun, RunStatus
from app.agent_runs.tokens import RUN_TOKEN_PREFIX, resolve_run_token
from app.auth.deps import require_password_ok
from app.auth.models import TokenScope, User, UserStatus
from app.auth.tokens import resolve_bearer
from app.core.db import SessionLocal
from app.projects.models import Project
from app.tasks.models import Task
from app.workflow import engine

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
    if run.task_id is None:  # an answering run works on a question, a draft run on its draft: never on a task
        raise ToolError("not_allowed_in_role")
    task = await db.get(Task, run.task_id)
    project = await db.get(Project, task.project_id) if task is not None else None
    if project is None or not isinstance(key, str) or key.strip().upper() != f"{project.key}-{task.number}".upper():
        raise ToolError("wrong_task")


async def live_run(db: AsyncSession, task: Task) -> AgentRun:
    """The calling run, re-read under the workflow lock (taken here, in the engine's order: task, workflow, then
    the run row), so it cannot end while the tool acts. The token resolver checked it when the request arrived,
    but a run can end mid-call: it must still be running (run_not_running)."""
    await engine.lock_task(db, task)
    run = (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.id == current_run.get().id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if run is None or run.status != RunStatus.running:
        raise HTTPException(status.HTTP_409_CONFLICT, "run_not_running")
    return run


async def _blanked_receive(run: AgentRun, receive: Receive) -> Receive:
    """The request read whole, with the run's secret values blanked out of every tools/call's arguments, replayed to
    the app. A body larger than the MCP server takes is passed on as it is: the server refuses it anyway."""
    from app.mcp_server.server import MAX_REQUEST_BYTES  # local: the server imports this module
    from app.secrets.blanking import blank_json
    from app.secrets.delivery import values_for_run

    chunks: list[bytes] = []
    size, more = 0, True
    while more:
        message = await receive()
        if message["type"] != "http.request":  # the client went away: hand that on
            return _replay([message])
        chunks.append(message.get("body", b""))
        size += len(chunks[-1])
        more = message.get("more_body", False)
        if size > MAX_REQUEST_BYTES:
            return _replay([{"type": "http.request", "body": b"".join(chunks), "more_body": more}], receive)
    body = b"".join(chunks)
    async with SessionLocal() as db:
        secrets = await values_for_run(db, run)
    if secrets:
        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
        calls = payload if isinstance(payload, list) else [payload]
        changed = False
        for call in calls:
            if isinstance(call, dict) and call.get("method") == "tools/call" and isinstance(call.get("params"), dict):
                call["params"]["arguments"] = blank_json(call["params"].get("arguments") or {}, secrets)
                changed = True
        if changed:
            body = json.dumps(payload).encode()
    return _replay([{"type": "http.request", "body": body, "more_body": False}])


def _replay(messages: list[Message], then: Receive | None = None) -> Receive:
    async def receive() -> Message:
        if messages:
            return messages.pop(0)
        if then is not None:
            return await then()
        return {"type": "http.disconnect"}

    return receive


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
        if run is not None:  # a run's secret values never reach what its tool calls store
            receive = await _blanked_receive(run, receive)
        reset = current_mcp_user_id.set(user_id)
        reset_run = current_run.set(run)
        try:
            await self.app(scope, receive, send)
        finally:
            current_run.reset(reset_run)
            current_mcp_user_id.reset(reset)
