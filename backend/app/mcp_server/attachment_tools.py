"""MCP tools for the files in a task's Attachments: list_attachments, and get_attachment for one file's download link
(and its picture, for an image). Images sent with messages reach the runs they were sent to, not these tools."""

import asyncio
import base64
import json
import uuid
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ImageContent, TextContent
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.config import get_settings
from app.mcp_server.auth import current_run, require_run_task
from app.mcp_server.auth import tool_session as _tool_session
from app.mcp_server.board_tools import freestyle_board, project_of
from app.tasks import file_links, service
from app.tasks.models import Task

# the largest image shown as a picture: the model takes 5 MB once base64-encoded, a third larger than the file
MAX_PICTURE_BYTES = 5 * 1024 * 1024 * 3 // 4


async def readable_task(db: AsyncSession, user: User, key: str) -> Task:
    """The task `key` names, when the caller may read it: a run token only its own task (a chat's turn: its chat's
    project), a person's token whatever they may read."""
    run = current_run.get()
    if run is not None and run.workflow_role == "freestyle":
        (await freestyle_board(db)).check(project_of(key))  # a freestyle turn reads its chat's project
    else:
        await require_run_task(db, key, reading=True)
    task, _ = await service.get_task_for(db, user, key)
    return task


def register_attachment_tools(mcp: MCPServer) -> None:
    @mcp.tool()
    async def list_attachments(key: str) -> list[dict[str, Any]]:
        """The files people attached to a task (e.g. PAY-12) in its Attachments section, oldest first: id, file
        name, type, size, whether it is an image, who attached it and when. Get one with get_attachment."""
        async with _tool_session() as (db, user):
            task = await readable_task(db, user, key)
            return await file_links.entries(db, await file_links.task_files(db, task))

    @mcp.tool()
    async def get_attachment(key: str, attachment_id: str) -> dict[str, Any]:  # or the same with the picture
        """One file of a task's Attachments: a download link that works for 15 minutes, for saving the file where
        you need it (e.g. `curl -fsSL -o assets/logo.png "<url>"`). An image is also shown to you as a picture."""
        async with _tool_session() as (db, user):
            task = await readable_task(db, user, key)
            try:
                att = await file_links.task_file(db, task, uuid.UUID(str(attachment_id)))
            except ValueError:
                att = None
            if att is None:
                raise ToolError("not_found")
            [out] = await file_links.entries(db, [att])
            url, expires_at = file_links.signed_link(att.id)
            out |= {
                "url": url,
                "expires_at": expires_at.isoformat(),
                "how": f'Save it with: curl -fsSL -o <path> "{url}" (the link stops working at '
                f"{expires_at:%H:%M} UTC: call get_attachment again for a new one).",
            }
            path = Path(get_settings().upload_dir) / att.storage_key
            if not att.image or att.size > MAX_PICTURE_BYTES or not path.is_file():
                return out
            data = await asyncio.to_thread(path.read_bytes)
            return CallToolResult(
                content=[
                    TextContent(type="text", text=json.dumps(out)),
                    ImageContent(type="image", data=base64.b64encode(data).decode(),
                                 mime_type=att.content_type),
                ],
                structured_content=out,
            )
