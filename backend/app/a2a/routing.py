"""Routing questions to answering sessions (A2A-2, A2A-5).

Runner connections live in the API process, so routing runs there too: when a question is asked, when a runner
reports its agents, when an answering run ends, and on a 60-second loop started with the app.
"""

import asyncio
import contextlib
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a import prompts
from app.a2a.models import Question, QuestionStatus
from app.agent_runs.models import ACTIVE_STATUSES, AgentRun
from app.agent_runs.tokens import issue_run_token
from app.agents.models import Agent, AgentBinding
from app.agents.service import owner_can_access
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.projects.models import Project
from app.runner.protocol import McpAccess, RunTask
from app.runner.registry import WORKFLOW_CAPABILITY, registry

log = logging.getLogger(__name__)

ROUTE_LIMIT = 50
MAX_ATTEMPTS = 3
ROUTE_SECONDS = 60


class NotSupported(Exception):
    """The run cannot be started (its question or binding is gone)."""


async def candidates(db: AsyncSession, q: Question) -> list[Agent]:
    """Bound agents of the target project's members, on a live runner that can run answering sessions, with a
    free slot, not tried for this question; the least busy first."""
    tried = {uuid.UUID(t) for t in q.tried_agent_ids or []}
    agents = (
        await db.execute(
            select(Agent)
            .join(AgentBinding, AgentBinding.agent_id == Agent.id)
            .where(AgentBinding.project_id == q.target_project_id, owner_can_access(q.target_project_id))
        )
    ).scalars().all()
    out: list[tuple[int, uuid.UUID, Agent]] = []
    for a in agents:
        conn = registry.conn_for_user(a.owner_id)
        if a.id in tried or conn is None or a.id not in conn.available:
            continue
        if not registry.supports(a.owner_id, WORKFLOW_CAPABILITY):
            continue
        running = await db.scalar(
            select(func.count()).select_from(AgentRun).where(
                AgentRun.agent_id == a.id, AgentRun.status.in_(ACTIVE_STATUSES)
            )
        )
        if running >= a.max_concurrent_runs:
            continue
        out.append((running, a.id, a))
    return [a for _, _, a in sorted(out, key=lambda t: (t[0], str(t[1])))]


async def route_question(db: AsyncSession, question_id: uuid.UUID) -> AgentRun | None:
    """Queues an answering run on the best candidate. The caller commits, then dispatches (DISPATCH_KEY)."""
    q = (
        await db.execute(
            select(Question).where(Question.id == question_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if q is None or q.status != QuestionStatus.queued:
        return None
    found = await candidates(db, q)
    if not found:
        return None
    agent = found[0]
    project = await db.get(Project, q.target_project_id)
    run = AgentRun(
        question_id=q.id, agent_id=agent.id, requested_by=q.asked_by_user_id or agent.owner_id,
        policy="read_only", prompt=prompts.answer_prompt(q, project.key),
    )
    db.add(run)
    q.status = QuestionStatus.routed
    await db.flush()
    from app.workflow import engine  # local: the engine imports the run service

    db.info.setdefault(engine._DISPATCH_KEY, set()).add(agent.owner_id)  # sent after the caller commits
    from app.a2a.service import (
        notify,  # local: the service imports this module's callers
    )

    await notify(db, q)
    return run


async def route_queued(db: AsyncSession) -> int:
    ids = (
        await db.execute(
            select(Question.id).where(Question.status == QuestionStatus.queued)
            .order_by(Question.created_at).limit(ROUTE_LIMIT)
        )
    ).scalars().all()
    routed = 0
    for qid in ids:
        if await route_question(db, qid) is not None:
            routed += 1
    return routed


async def route_and_dispatch() -> None:
    from app.workflow import engine  # local: the engine imports the run service

    async with SessionLocal() as db:
        await route_queued(db)
        await engine.dispatch_queued(db)
        await db.commit()


async def route_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await route_and_dispatch()
        except Exception:
            log.exception("question routing failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), ROUTE_SECONDS)


async def start_fields(db: AsyncSession, run: AgentRun) -> tuple[RunTask, str, dict]:
    """(RunTask, local_path, v2 fields) for an answering run's run_start: read-only, a synthetic task key
    `<TARGET>-Q<n>` (its own worktree and branch on the runner), and the run's MCP token."""
    q = await db.get(Question, run.question_id)
    if q is None:
        raise NotSupported("question_gone")
    project = await db.get(Project, q.target_project_id)
    owner_id = await db.scalar(select(Agent.owner_id).where(Agent.id == run.agent_id))
    local_path = await db.scalar(
        select(AgentBinding.local_path).where(
            AgentBinding.agent_id == run.agent_id, AgentBinding.project_id == q.target_project_id
        )
    )
    if local_path is None:
        raise NotSupported("agent_not_bound")
    allowed = await db.scalar(select(Agent.id).where(Agent.id == run.agent_id, owner_can_access(project.id)))
    if allowed is None or owner_id is None:
        raise NotSupported("owner_lost_access")
    task = RunTask(key=f"{project.key}-Q{q.number}", title=q.title, description_md="", project_key=project.key)
    fields = {
        "role": "answer",
        "mcp": McpAccess(url=get_settings().public_url.rstrip("/") + "/api/mcp", token=issue_run_token(run)),
    }
    return task, local_path, fields


async def on_answer_run_finished(db: AsyncSession, run: AgentRun) -> None:
    """An answering run ended. If it left its question still routed (no answer: failed, cancelled, or done
    without submit_answer), the agent is excluded and the question tries again, at most MAX_ATTEMPTS times."""
    q = (
        await db.execute(
            select(Question).where(Question.id == run.question_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if q is None or q.status != QuestionStatus.routed:
        return
    still = await db.scalar(
        select(AgentRun.id).where(AgentRun.question_id == q.id, AgentRun.id != run.id,
                                  AgentRun.status.in_(ACTIVE_STATUSES)).limit(1)
    )
    if still is not None:
        return
    tried = list(q.tried_agent_ids or [])
    if str(run.agent_id) not in tried:
        tried.append(str(run.agent_id))
    q.tried_agent_ids = tried
    q.attempts += 1
    q.status = QuestionStatus.needs_human if q.attempts >= MAX_ATTEMPTS else QuestionStatus.queued
    await db.flush()
    from app.a2a.service import notify

    await notify(db, q)
    if q.status == QuestionStatus.queued:
        await route_question(db, q.id)

