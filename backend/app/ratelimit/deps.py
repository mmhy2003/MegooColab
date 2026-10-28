"""The AI limit: calls that make the server ask an AI provider while the person waits.

Counted per credential (the middleware's `current_subject`), so a browser, a personal token and each agent run have
their own budget. MCP tools turn the refusal into the tool error `rate_limited`.
"""

from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import HTTPConnection

from app.ratelimit import limits, store
from app.ratelimit.clientip import client_ip
from app.ratelimit.middleware import current_subject


async def check_ai(conn: HTTPConnection | None = None) -> None:
    limit = limits.get("ai_user")
    subject = current_subject.get() or "unknown"
    ip = client_ip(conn) if conn is not None else "unknown"
    await store.raise_if_blocked(await store.hit(limit, subject), limit, ip=ip, subject=subject)


async def ai_or_tool_error() -> None:
    """`check_ai` for MCP tools: a refusal is the tool error `rate_limited`."""
    try:
        await check_ai()
    except store.RateLimited:
        raise ToolError("rate_limited") from None
