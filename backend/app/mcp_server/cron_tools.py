"""The cron MCP tool: a cron's run reports what it found, once, at the end. Cron runs only, for their own run."""

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.crons import report
from app.mcp_server.auth import current_run, tool_session


def register_cron_tools(mcp: MCPServer) -> None:
    @mcp.tool()
    async def submit_cron_report(
        summary: str,
        findings: list[dict[str, Any]],
        checked: str = "",
        nothing_new: bool = False,
        document_md: str | None = None,
    ) -> dict[str, Any]:
        """Report this cron run, once, at the end. `summary`: one or two sentences. `findings`: real problems, each
        {title, detail, new_task?, existing_task_key?} — new_task asks for a task (when your cron may open tasks),
        existing_task_key names an open task of the project that already tracks it. `checked`: what you looked at.
        `nothing_new`: nothing changed since the last run. `document_md`: the whole new document (when your cron keeps
        a Knowledge Base document)."""
        run = current_run.get()
        if run is None or run.cron_run_id is None:
            raise ToolError("not_allowed_in_role")
        async with tool_session() as (db, _user):  # REST errors become tool errors with their code
            return await report.apply_report(db, run, summary=summary, findings=findings, checked=checked,
                                             nothing_new=nothing_new, document_md=document_md)
