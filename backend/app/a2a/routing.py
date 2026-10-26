"""Routing questions to answering sessions (A2A-2, A2A-5). Task 3 fills in the bodies."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun


class NotSupported(Exception):
    """Answering sessions are not available yet."""


async def start_fields(db: AsyncSession, run: AgentRun):
    """(RunTask, local_path, v2 fields) for an answering run's run_start."""
    raise NotSupported


async def on_answer_run_finished(db: AsyncSession, run: AgentRun) -> None:
    """An answering run ended."""
