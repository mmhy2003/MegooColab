"""Board tools beyond creating and editing tasks: deleting a task, and sprints. A person's token may use them with the
person's rights. A freestyle chat's turn may too, on the chat's own project only, with its agent owner's rights: each
change it makes is a line in the chat (agent_board_changed on the chat round), and the changed task's events link
back to the chat. Every other run token is refused."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun
from app.auth.models import User
from app.mcp_server.auth import current_run
from app.mcp_server.auth import tool_session as _tool_session
from app.projects.access import get_project_for
from app.projects.models import Project
from app.sprints import actions, service as sprint_service
from app.sprints.models import Sprint
from app.sprints.schemas import SprintIn, SprintOut, SprintPatch
from app.tasks import service
from app.tasks.models import Task
from app.tasks.removal import remove_task
from app.workflow.models import RunRole


# what a chat line says changed when an agent edits a task
BOARD_FIELDS = ("title", "description_md", "type", "priority", "story_points")


@dataclass
class Board:
    """A freestyle turn working on its chat's project."""

    run: AgentRun
    round: Task  # the turn's own task: its chat round
    project: Project
    origin: dict[str, str] | None  # the chat: {"id", "title"}

    def check(self, project_key: str | None) -> None:
        if not isinstance(project_key, str) or project_key.strip().upper() != self.project.key.upper():
            raise ToolError("wrong_project")

    def check_task(self, task: Task) -> None:
        """Its own project's board tasks only: never a chat round (its own or another chat's)."""
        if task.project_id != self.project.id:
            raise ToolError("wrong_project")
        if task.in_chat:
            raise ToolError("task_not_found")


async def freestyle_board(db: AsyncSession) -> Board | None:
    """None for a person's token; the Board for a freestyle turn; not_allowed_in_role for any other run."""
    run = current_run.get()
    if run is None:
        return None
    if run.workflow_role != RunRole.freestyle or run.task_id is None:
        raise ToolError("not_allowed_in_role")
    from app.chats.models import Chat  # local: the chats modules import the MCP tools' services

    rnd = await db.get(Task, run.task_id)
    if rnd is None:
        raise ToolError("not_allowed_in_role")
    project = await db.get(Project, rnd.project_id)
    chat = await db.get(Chat, rnd.chat_id) if rnd.chat_id else None
    return Board(run, rnd, project, {"id": str(chat.id), "title": chat.title} if chat else None)


def project_of(key: str) -> str:
    return key.rsplit("-", 1)[0] if isinstance(key, str) else ""


@contextmanager
def from_chat(board: Board | None) -> Iterator[None]:
    """While a freestyle turn acts, the changed tasks' events carry its chat."""
    token = service.event_origin.set(board.origin if board else None)
    try:
        yield
    finally:
        service.event_origin.reset(token)


async def board_line(db: AsyncSession, board: Board | None, action: str, **data: Any) -> None:
    """One line in the chat for one change the turn made."""
    if board is None:
        return
    await service.record_event(db, board.round, None, "agent_board_changed", {
        "action": action, "project": board.project.key, **data,
        "agent_id": str(board.run.agent_id), "run_id": str(board.run.id),
    })


def task_key(project: Project, task: Task) -> str:
    return f"{project.key}-{task.number}"


async def _sprint(db: AsyncSession, user: User, board: Board | None, ref: str, project_key: str | None,
                  manage: bool) -> Sprint:
    """A sprint by id, or by name within `project_key` (a freestyle turn: its chat's project by default)."""
    try:
        sprint_id = uuid.UUID(str(ref))
    except ValueError:
        sprint_id = None
    if sprint_id is None:
        if project_key is None and board is not None:
            project_key = board.project.key
        if not project_key:
            raise ToolError("project_key_needed")
        if board is not None:
            board.check(project_key)
        project = await get_project_for(db, user, project_key)
        sprint_id = (await actions.sprint_named(db, project, ref)).id
    sprint = await actions.sprint_for(db, user, sprint_id, manage=manage)
    if board is not None and sprint.project_id != board.project.id:
        raise ToolError("wrong_project")
    return sprint


def _out(sprint: Sprint) -> dict[str, Any]:
    return SprintOut.model_validate(sprint).model_dump(mode="json")


def register_board_tools(mcp: MCPServer) -> None:
    @mcp.tool()
    async def delete_task(key: str) -> dict[str, str]:
        """Delete a task for good (its reporter or a project manager may). An epic's tasks stay, outside any epic;
        a task's subtasks go with it."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)
            if board is not None:
                board.check(project_of(key))
            task, project = await service.get_task_for(db, user, key, write=True)
            if board is not None:
                board.check_task(task)
            title = task.title
            with from_chat(board):
                await remove_task(db, user, project, task)
            await board_line(db, board, "task_deleted", key=key.strip().upper(), title=title)
            return {"deleted": key.strip().upper()}

    @mcp.tool()
    async def list_sprints(project_key: str) -> list[dict[str, Any]]:
        """A project's sprints, oldest first: id, name, goal, dates and state (planned, active or completed)."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)
            if board is not None:
                board.check(project_key)
            project = await get_project_for(db, user, project_key)
            sprint_service.require_sprints(project)
            rows = await db.execute(select(Sprint).where(Sprint.project_id == project.id)
                                    .order_by(Sprint.start_date, Sprint.created_at))
            return [_out(s) for s in rows.scalars()]

    @mcp.tool()
    async def create_sprint(project_key: str, name: str, start_date: str, end_date: str,
                            goal: str = "") -> dict[str, Any]:
        """Plan a sprint (needs the project's manage rights). Dates are YYYY-MM-DD; it starts only with start_sprint."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)
            if board is not None:
                board.check(project_key)
            try:
                body = SprintIn(name=name, goal=goal, start_date=start_date, end_date=end_date)
            except ValidationError:
                raise ToolError("invalid_input") from None
            project = await get_project_for(db, user, project_key, write=True)
            sprint = await actions.create(db, user, project, body)
            await board_line(db, board, "sprint_created", sprint=sprint.name, sprint_id=str(sprint.id),
                             start=sprint.start_date.isoformat(), end=sprint.end_date.isoformat())
            return _out(sprint)

    @mcp.tool()
    async def update_sprint(sprint: str, name: str | None = None, goal: str | None = None,
                            start_date: str | None = None, end_date: str | None = None,
                            project_key: str | None = None) -> dict[str, Any]:
        """Change a sprint's name, goal or dates (YYYY-MM-DD). `sprint` is its id, or its name with `project_key`."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)
            row = await _sprint(db, user, board, sprint, project_key, manage=True)
            try:
                body = SprintPatch(name=name, goal=goal, start_date=start_date, end_date=end_date)
            except ValidationError:
                raise ToolError("invalid_input") from None
            await actions.update(db, row, body)
            await board_line(db, board, "sprint_changed", sprint=row.name, sprint_id=str(row.id))
            return _out(row)

    @mcp.tool()
    async def start_sprint(sprint: str, project_key: str | None = None) -> dict[str, Any]:
        """Start a planned sprint (one active sprint per project). `sprint` is its id, or its name with
        `project_key`."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)
            row = await _sprint(db, user, board, sprint, project_key, manage=True)
            await sprint_service.start(db, row)
            await actions.changed(db, row)
            await board_line(db, board, "sprint_started", sprint=row.name, sprint_id=str(row.id))
            return _out(row)

    @mcp.tool()
    async def complete_sprint(sprint: str, move_open_to: str = "backlog",
                              project_key: str | None = None) -> dict[str, Any]:
        """Complete the active sprint. Its unfinished tasks go to the backlog, or to the planned sprint named in
        `move_open_to` (id or name)."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)
            row = await _sprint(db, user, board, sprint, project_key, manage=True)
            target: str | uuid.UUID = "backlog"
            if move_open_to.strip().lower() != "backlog":
                target = (await _sprint(db, user, board, move_open_to, project_key, manage=True)).id
            await sprint_service.complete(db, row, target)
            await actions.changed(db, row)
            await board_line(db, board, "sprint_completed", sprint=row.name, sprint_id=str(row.id))
            return _out(row)

    @mcp.tool()
    async def delete_sprint(sprint: str, project_key: str | None = None) -> dict[str, str]:
        """Delete a sprint: its tasks lose the sprint, and open ones are back in the backlog."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)
            row = await _sprint(db, user, board, sprint, project_key, manage=True)
            name = row.name
            await actions.delete(db, user, row)
            await board_line(db, board, "sprint_deleted", sprint=name)
            return {"deleted": name}

    @mcp.tool()
    async def set_task_sprint(key: str, sprint: str | None) -> dict[str, Any]:
        """Put a story, task or bug in a planned or active sprint (its id or name), or take it out with null."""
        async with _tool_session() as (db, user):
            board = await freestyle_board(db)
            if board is not None:
                board.check(project_of(key))
            task, project = await service.get_task_for(db, user, key, write=True)
            if board is not None:
                board.check_task(task)
            row = await _sprint(db, user, board, sprint, project.key, manage=False) if sprint else None
            with from_chat(board):
                await actions.set_task_sprint(db, user, project, task, row.id if row else None)
            await board_line(db, board, "sprint_set", key=task_key(project, task), title=task.title,
                             sprint=row.name if row else None, sprint_id=str(row.id) if row else None)
            return (await service.task_out(db, task, user)).model_dump(mode="json")
