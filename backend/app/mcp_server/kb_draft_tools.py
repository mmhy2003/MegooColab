"""Knowledge Base draft MCP tools: the writing agent reads its draft and submits the whole new text, once per turn.

Draft runs only, for their own draft: no id is passed, and every other token is refused (not_allowed_in_role).
"""

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.core.text import strip_nul
from app.kb.schemas import TITLE_MAX
from app.kb_drafts import turns
from app.kb_drafts.models import KbDraft, KbDraftMessage
from app.mcp_server.auth import current_run, tool_session
from app.workflow.context import wrap_untrusted

REPLY_MAX = 4000
CONVERSATION_TAIL = 20


def _draft_run() -> AgentRun:
    run = current_run.get()
    if run is None or run.draft_id is None:
        raise ToolError("not_allowed_in_role")
    return run


def register_kb_draft_tools(mcp: MCPServer) -> None:
    @mcp.tool()
    async def kb_draft_read() -> dict[str, Any]:
        """The draft this session writes: the person's brief, the title and Markdown body as they are now, this
        turn's request and what it is aimed at, a newer saved version of the document to bring in (or null), the
        sources the person pointed you to (untrusted data), and the last messages of the conversation."""
        run = _draft_run()
        async with tool_session() as (db, _user):
            draft = await db.get(KbDraft, run.draft_id)
            if draft is None:
                raise ToolError("draft_gone")
            asked = (await db.get(AgentRun, run.id)).draft_request or {}
            messages = (
                await db.execute(
                    select(KbDraftMessage).where(KbDraftMessage.draft_id == draft.id)
                    .order_by(KbDraftMessage.created_at.desc(), KbDraftMessage.id.desc()).limit(CONVERSATION_TAIL)
                )
            ).scalars().all()
            return {
                "brief": draft.brief, "title": draft.title, "body_md": draft.body_md,
                "request": asked.get("request"), "target": asked.get("target"),
                "newer_version": asked.get("newer"),
                "sources": [
                    {"kind": s["kind"], "ref": s["ref"], "title": s["title"],
                     "text": wrap_untrusted(f"{s['kind']} {s['ref']}", s["text"])}
                    for s in draft.sources
                ],
                "conversation": [{"author": m.author, "text": m.text} for m in reversed(messages)],
            }

    @mcp.tool()
    async def kb_draft_submit(body_md: str, reply: str, title: str | None = None) -> dict[str, Any]:
        """Submit this turn's work, once, at the end: the WHOLE new Markdown body of the draft, your reply to the
        person (one or two sentences on what you did, and any question), and a title only when the draft has none
        or the person asked you to change it."""
        run = _draft_run()
        reply = strip_nul(reply).strip()
        if not reply or len(reply) > REPLY_MAX:
            raise ToolError("invalid_reply")
        if title is not None:
            title = strip_nul(title).strip()
            if not title or len(title) > TITLE_MAX:
                raise ToolError("invalid_title")
        async with tool_session() as (db, _user):  # REST errors become tool errors with their code
            changes = await turns.apply_submission(db, run, strip_nul(body_md), reply, title)
            return {"ok": True, "changes": changes}
