"""MCP server: task tools and workflow tools for coding agents, over Streamable HTTP at /api/mcp.

Every tool opens its own DB session, loads the token owner and calls the same service
functions as the REST API, so permissions, events and task history are identical.
A run token (`mgr_`) may read and comment on its own task only, and use the workflow tools of its role
(app/mcp_server/workflow_tools.py); the other task tools refuse it.
"""

import base64
import json
import uuid
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, ImageContent, TextContent
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Route
from starlette.types import ASGIApp

from app.agents.models import Agent
from app.core.config import get_settings
from app.images import delivery as image_delivery
from app.mcp_server.a2a_tools import register_a2a_tools
from app.mcp_server.auth import (
    McpBearerAuth,
    current_run,
    live_run,
    refuse_run_token,
    require_cron_reading,
    require_run_task,
)
from app.mcp_server.auth import tool_session as _tool_session
from app.mcp_server.board_tools import (
    BOARD_FIELDS,
    board_line,
    freestyle_board,
    from_chat,
    project_of,
    register_board_tools,
    task_key,
)
from app.mcp_server.cron_tools import register_cron_tools
from app.mcp_server.kb_draft_tools import register_kb_draft_tools
from app.mcp_server.kb_tools import register_kb_tools
from app.mcp_server.memory_tools import register_memory_tools
from app.mcp_server.workflow_tools import register_workflow_tools
from app.projects.access import accessible_project_ids, get_project_for
from app.projects.models import BoardColumn, Project
from app.tasks import service
from app.tasks.activity import CommentIn, activity_items, create_comment
from app.tasks.models import Priority, Task, TaskType
from app.tasks.schemas import MoveIn, TaskCreate, TaskUpdate
from app.workflow import engine
from app.workflow.models import Driver, TaskWorkflow

MCP_PATH = "/api/mcp"
ACTIVITY_LIMIT = 20
MAX_REQUEST_BYTES = 8 * 1024 * 1024


def _json(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


async def _with_images(db: AsyncSession, task: Task, out: dict[str, Any]) -> dict[str, Any] | CallToolResult:
    """A connect-only agent (the person's own) gets the task's images here, as image content after the JSON: a
    runner-driven one has them in its prompt. Each one returned counts as delivered."""
    wf = await db.get(TaskWorkflow, task.id)
    if wf is None or wf.driver != Driver.connect_only:
        return out
    atts, note = await image_delivery.images_for_mcp(db, task)
    root = Path(get_settings().upload_dir)
    shown = [(a, root / a.storage_key) for a in atts]
    shown = [(a, path) for a, path in shown if path.is_file()]
    if not shown:
        return out
    out["images_note"] = note
    image_delivery.mark_sent([a for a, _ in shown], None)
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(out)),
            *(ImageContent(type="image", data=base64.b64encode(path.read_bytes()).decode(), mime_type=a.content_type)
              for a, path in shown),
        ],
        structured_content=out,
    )


async def _column_by_name(db: AsyncSession, project: Project, name: str) -> BoardColumn:
    cols = (await db.execute(select(BoardColumn).where(BoardColumn.project_id == project.id))).scalars()
    for col in cols:
        if col.name.casefold() == name.strip().casefold():
            return col
    raise ToolError("invalid_column")


async def _from_line(db: AsyncSession, asking: Task) -> str:
    """Where a task a freestyle turn created came from: its chat, else the task the turn worked on."""
    from app.chats.models import Chat  # local: the chats modules import the MCP tools' services

    chat = await db.get(Chat, asking.chat_id) if asking.chat_id else None
    if chat is not None:
        return f"From chat: [{chat.title}](/chats/{chat.id})"
    project = await db.get(Project, asking.project_id)
    return f"From {project.key}-{asking.number}"


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
        type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Tasks of a project. `assignee` is a user id, or `agent:<agent id>`; `column` is a column name;
        `q` matches titles; `mine` keeps tasks assigned to me or to one of my agents; `type` keeps one type
        (epic, story, task, bug or subtask): `type="epic"` lists the project's epics."""
        async with _tool_session() as (db, user):
            run = current_run.get()
            if run is not None and run.workflow_role == "freestyle":
                (await freestyle_board(db)).check(project_key)  # a freestyle turn reads its chat's project
            else:
                await require_cron_reading(db, project_key)  # a cron's run reads its own project's tasks; others none
            project = await get_project_for(db, user, project_key)
            column_id = (await _column_by_name(db, project, column)).id if column else None
            try:
                type_ = TaskType(type) if type else None
            except ValueError:
                raise ToolError("invalid_input") from None
            tasks = await service.list_tasks(db, project, type_=type_, assignee=assignee, column=column_id, q=q)
            if mine:
                my_agents = set((await db.execute(select(Agent.id).where(Agent.owner_id == user.id))).scalars())
                tasks = [t for t in tasks if t.assignee_user_id == user.id or t.assignee_agent_id in my_agents]
            return await _task_summaries(db, project, tasks)

    @mcp.tool()
    async def get_task(key: str) -> dict[str, Any]:
        """A task by key (e.g. PAY-12) with its last 20 activity items (comments, events and questions), and the
        images people sent you with their messages, after the task's JSON."""
        async with _tool_session() as (db, user):
            run = current_run.get()
            if run is not None and run.workflow_role == "freestyle":
                (await freestyle_board(db)).check(project_of(key))  # a freestyle turn reads its chat's project
            else:
                await require_run_task(db, key, reading=True)
            task, _ = await service.get_task_for(db, user, key)
            out = _json(await service.task_out(db, task, user))
            out["activity"] = [_json(i) for i in await activity_items(db, task, ACTIVITY_LIMIT)]
            return await _with_images(db, task, out)

    @mcp.tool()
    async def create_task(
        project_key: str,
        title: str,
        type: str = "task",
        description_md: str = "",
        parent_key: str | None = None,
        assignee_agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a task in the project's first column. `type` is epic, story, task, bug or subtask.
        In a freestyle chat: only on the chat's own project, unassigned, with a link back to the chat."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)  # a person's token, or a freestyle turn: nothing else creates tasks
            if board is not None:
                board.check(project_key)
            asking = board.round if board is not None else None
            if asking is not None:
                assignee_agent_id, parent_key = None, None  # it's reviewed before anyone takes it
                description_md = f"{description_md.rstrip()}\n\n{await _from_line(db, asking)}".lstrip()
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
            out = await service.task_out(db, task, user)
            if asking is not None:
                await service.record_event(db, asking, None, "agent_task_created", {
                    "key": out.key, "title": task.title, "task_id": str(task.id), "type": str(task.type),
                    "agent_id": str(board.run.agent_id), "run_id": str(board.run.id),
                })
            return _json(out)

    @mcp.tool()
    async def update_task(
        key: str,
        title: str | None = None,
        description_md: str | None = None,
        priority: str | None = None,
        story_points: int | None = None,
        type: str | None = None,
        epic_key: str | None = None,
    ) -> dict[str, Any]:
        """Change a task's title, description, priority (lowest, low, medium, high or highest), story points or
        type (epic, story, task, bug or subtask). `epic_key` puts it under that epic; an empty string takes it out
        of its epic."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)
            if board is not None:
                board.check(project_of(key))
            task, project = await service.get_task_for(db, user, key, write=True)
            if board is not None:
                board.check_task(task)
            try:
                wanted = {
                    "title": title,
                    "description_md": description_md,
                    "priority": Priority(priority) if priority else None,
                    "story_points": story_points,
                    "type": TaskType(type) if type else None,
                }
                data = TaskUpdate(**{k: v for k, v in wanted.items() if v is not None})
            except ValueError:
                raise ToolError("invalid_input") from None
            epic = None
            if epic_key:
                epic, _ = await service.get_task_for(db, user, epic_key)
                if epic.project_id != project.id or epic.in_chat:
                    raise ToolError("invalid_parent")
            if epic_key is not None:
                data.parent_id = epic.id if epic else None
            before = {name: getattr(task, name) for name in BOARD_FIELDS}
            parent_before = task.parent_id
            with from_chat(board):
                await service.update_task(db, user, project, task, data)
            await service.task_changed(db, task)
            changed_key = task_key(project, task)
            if task.parent_id != parent_before:
                await board_line(db, board, "epic_set", key=changed_key, title=task.title,
                                 epic=task_key(project, epic) if epic else None)
            fields = [name for name in BOARD_FIELDS if getattr(task, name) != before[name]]
            if fields:
                await board_line(db, board, "task_changed", key=changed_key, title=task.title, fields=fields)
            return _json(await service.task_out(db, task, user))

    @mcp.tool()
    async def move_task(key: str, column: str) -> dict[str, Any]:
        """Move a task to the end of the named column (case-insensitive), e.g. "In Progress"."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)
            if board is not None:
                board.check(project_of(key))
            task, project = await service.get_task_for(db, user, key, write=True)
            if board is not None:
                board.check_task(task)
            col = await _column_by_name(db, project, column)
            with from_chat(board):
                await service.move_task(db, user, project, task, MoveIn(column_id=col.id))
            await service.task_changed(db, task)
            await board_line(db, board, "task_moved", key=task_key(project, task), title=task.title, column=col.name)
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

    register_board_tools(mcp)
    register_workflow_tools(mcp)
    register_kb_tools(mcp)
    register_memory_tools(mcp)
    register_a2a_tools(mcp)
    register_kb_draft_tools(mcp)
    register_cron_tools(mcp)

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
