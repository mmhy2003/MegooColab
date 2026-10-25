"""Run-scoped MCP tokens (AGT-33): `mgr_` + 32 random bytes, valid only while their run is running.

Only the SHA-256 hash is stored, on the run. The raw value exists in the run_start message and nowhere else.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.auth.models import User, UserStatus
from app.core.security import hash_token

RUN_TOKEN_PREFIX = "mgr_"


def issue_run_token(run: AgentRun) -> str:
    """Give the run a fresh token (replacing any earlier one) and return the raw value."""
    raw = RUN_TOKEN_PREFIX + secrets.token_urlsafe(32)
    run.mcp_token_hash = hash_token(raw)
    return raw


async def resolve_run_token(db: AsyncSession, raw: str) -> tuple[User, AgentRun] | None:
    """The agent's owner and the run behind a raw run token, or None unless the run is running and the
    owner is active."""
    if not raw.startswith(RUN_TOKEN_PREFIX):
        return None
    run = (
        await db.execute(
            select(AgentRun).where(AgentRun.mcp_token_hash == hash_token(raw), AgentRun.status == RunStatus.running)
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    owner_id = await db.scalar(select(Agent.owner_id).where(Agent.id == run.agent_id))
    user = await db.get(User, owner_id) if owner_id is not None else None
    if user is None or user.status != UserStatus.active:
        return None
    return user, run
