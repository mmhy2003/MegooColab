"""MCP server: task tools and workflow tools for coding agents, over Streamable HTTP at /api/mcp.

Every tool opens its own DB session, loads the token owner and calls the same service
functions as the REST API, so permissions, events and task history are identical.
A run token (`mgr_`) may read and comment on its own task only, and use the workflow tools of its role
(app/mcp_server/workflow_tools.py); the other task tools refuse it.
"""

import uuid
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Route
from starlette.types import ASGIApp

from app.agents.models import Agent
from app.mcp_server.auth import (
    McpBearerAuth,
    current_run,
    live_run,
    refuse_run_token,
    require_run_task,
)
from app.mcp_server.auth import tool_session as _tool_session
from app.mcp_server.kb_tools import register_kb_tools
from app.mcp_server.workflow_tools import register_workflow_tools
from app.projects.access import accessible_project_ids, get_project_for
from app.projects.models import BoardColumn, Project
from app.tasks import service
from app.tasks.activity import CommentIn, activity_items, create_comment
from app.tasks.models import Priority, Task, TaskType
from app.tasks.schemas import MoveIn, TaskCreate, TaskUpdate
from app.workflow import engine

MCP_PATH = "/api/mcp"
ACTIVITY_LIMIT = 20
MAX_REQUEST_BYTES = 8 * 1024 * 1024


def _json(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


async def _column_by_name(db: AsyncSession, project: Project, name: str) -> BoardColumn:
    cols = (await db.execute(select(BoardColumn).where(BoardColumn.project_id == project.id))).scalars()
    for col in cols:
        if col.name.casefold() == name.strip().casefold():
            return col
    raise ToolError("invalid_column")


async def _task_summaries(db: AsyncSession, project: Project, tasks: list[Task]) -> list[dict[str, Any]]:
    names = dict(
        (await db.execute(select(BoardColumn.id, BoardColumn.name).where(BoardColumn.project_id == project.id))).all()
    )
    return [
        {
            "key": f"{project.key}-{t.number}",
            "title": t.title,
            "type": str(t.type),
            "priority": str(t.priority),
            "column": names.get(t.column_id),
            "story_points": t.story_points,
            "assignee_user_id": str(t.assignee_user_id) if t.assignee_user_id else None,
            "assignee_agent_id": str(t.assignee_agent_id) if t.assignee_agent_id else None,
        }
        for t in tasks
    ]


def build_mcp() -> tuple[MCPServer, ASGIApp]:
    """A fresh server and its auth-wrapped endpoint (a session manager can only run once)."""
    mcp = MCPServer("MegooColab")

    @mcp.tool()
    async def whoami() -> dict[str, Any]:
        """The MegooColab user this token belongs to."""
        async with _tool_session() as (_, user):
            return {"id": str(user.id), "name": user.name, "email": user.email, "role": str(user.role)}

    @mcp.tool()
    async def list_projects() -> list[dict[str, Any]]:
        """Projects the token owner can access."""
        refuse_run_token()
        async with _tool_session() as (db, user):
            allowed = await accessible_project_ids(db, user)
            stmt = select(Project).order_by(Project.key)
            if allowed is not None:
                stmt = stmt.where(Project.id.in_(allowed))
            projects = (await db.execute(stmt)).scalars()
            return [{"key": p.key, "name": p.name, "description": p.description} for p in projects]

    @mcp.tool()
    async def list_tasks(
        project_key: str,
        assignee: str | None = None,
        column: str | None = None,
        q: str | None = None,
        mine: bool = False,
    ) -> list[dict[str, Any]]:
        """Tasks of a project. `assignee` is a user id, or `agent:<agent id>`; `column` is a column name;
        `q` matches titles; `mine` keeps tasks assigned to me or to one of my agents."""
        refuse_run_token()
        async with _tool_session() as (db, user):
            project = await get_project_for(db, user, project_key)
            column_id = (await _column_by_name(db, project, column)).id if column else None
            tasks = await service.list_tasks(db, project, assignee=assignee, column=column_id, q=q)
            if mine:
                my_agents = set((await db.execute(select(Agent.id).where(Agent.owner_id == user.id))).scalars())
                tasks = [t for t in tasks if t.assignee_user_id == user.id or t.assignee_agent_id in my_agents]
            return await _task_summaries(db, project, tasks)

    @mcp.tool()
    async def get_task(key: str) -> dict[str, Any]:
        """A task by key (e.g. PAY-12) with its last 20 activity items (comments, events and questions)."""
        async with _tool_session() as (db, user):
            await require_run_task(db, key)
            task, _ = await service.get_task_for(db, user, key)
            out = _json(await service.task_out(db, task, user))
            out["activity"] = [_json(i) for i in await activity_items(db, task, ACTIVITY_LIMIT)]
            return out

    @mcp.tool()
    async def create_task(
        project_key: str,
        title: str,
        type: str = "task",
        description_md: str = "",
        parent_key: str | None = None,
        assignee_agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a task in the project's first column. `type` is epic, story, task, bug or subtask."""
        refuse_run_token()
        async with _tool_session() as (db, user):
            project = await get_project_for(db, user, project_key, write=True)
            try:
                data = TaskCreate(
                    title=title,
                    type=TaskType(type),
                    description_md=description_md,
                    assignee_agent_id=uuid.UUID(assignee_agent_id) if assignee_agent_id else None,
                )
            except ValueError:
                raise ToolError("invalid_input") from None
            if parent_key:
                parent, _ = await service.get_task_for(db, user, parent_key)
                if parent.project_id != project.id:
                    raise ToolError("invalid_parent")
                data.parent_id = parent.id
            task = await service.create_task(db, user, project, data)
            await service.task_changed(db, task, "task.created")
            return _json(await service.task_out(db, task, user))

    @mcp.tool()
    async def update_task(
        key: str,
        title: str | None = None,
        description_md: str | None = None,
        priority: str | None = None,
        story_points: int | None = None,
    ) -> dict[str, Any]:
        """Change a task's title, description, priority (lowest, low, medium, high or highest) or story points."""
        refuse_run_token()
        async with _tool_session() as (db, user):
            task, project = await service.get_task_for(db, user, key, write=True)
            try:
                wanted = {
                    "title": title,
                    "description_md": description_md,
                    "priority": Priority(priority) if priority else None,
                    "story_points": story_points,
                }
                data = TaskUpdate(**{k: v for k, v in wanted.items() if v is not None})
            except ValueError:
                raise ToolError("invalid_input") from None
            await service.update_task(db, user, project, task, data)
            await service.task_changed(db, task)
            return _json(await service.task_out(db, task, user))

    @mcp.tool()
    async def move_task(key: str, column: str) -> dict[str, Any]:
        """Move a task to the end of the named column (case-insensitive), e.g. "In Progress"."""
        refuse_run_token()
        async with _tool_session() as (db, user):
            task, project = await service.get_task_for(db, user, key, write=True)
            col = await _column_by_name(db, project, column)
            await service.move_task(db, user, project, task, MoveIn(column_id=col.id))
            await service.task_changed(db, task)
            await engine.dispatch_queued(db)  # a move into working may have started the workflow
            return _json(await service.task_out(db, task, user))

    @mcp.tool()
    async def comment_on_task(key: str, body_md: str) -> dict[str, str]:
        """Add a comment (markdown) to a task."""
        try:
            body = CommentIn(body_md=body_md).body_md  # same rules as the REST schema (NULs stripped, not empty)
        except ValidationError:
            raise ToolError("invalid_input") from None
        async with _tool_session() as (db, user):
            await require_run_task(db, key)
            if current_run.get() is not None:  # a run that ended mid-call no longer speaks on the task
                task, _ = await service.get_task_for(db, user, key, write=True)
                await live_run(db, task)
            comment = await create_comment(db, user, key, body)
            return {"comment_id": str(comment.id)}

    register_workflow_tools(mcp)
    register_kb_tools(mcp)

    http_app = mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        # A whole request is capped (413). It must hold a 2 MB mockup even once JSON-escaped; every field is
        # capped again by its own limit (too_large).
        max_request_body_size=MAX_REQUEST_BYTES,
        # Authenticated by bearer token, and served behind a proxy under any public host name
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    route = next(r for r in http_app.routes if isinstance(r, Route) and r.path == MCP_PATH)
    return mcp, McpBearerAuth(route.endpoint)
