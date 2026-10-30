"""Routing questions to answering sessions (A2A-2, A2A-5).

Runner connections live in the API process, so routing runs there too: when a question is asked, when a runner
reports its agents, when an answering run ends, and on a 60-second loop started with the app.
"""

import asyncio
import contextlib
import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a import prompts
from app.a2a.models import Question, QuestionStatus
from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunStatus
from app.agent_runs.tokens import issue_run_token
from app.agents.models import Agent, AgentBinding
from app.agents.service import owner_can_access
from app.audit import service as audit
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.projects.models import Project
from app.runner.protocol import McpAccess, RunTask
from app.runner.registry import WORKFLOW_CAPABILITY, registry

log = logging.getLogger(__name__)

ROUTE_LIMIT = 50
MAX_ATTEMPTS = 3
ROUTE_SECONDS = 60
# an answering run still queued this long on an agent that is not available is given up (another agent tries)
STALE_QUEUED_SECONDS = 300


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
        if a.id in tried or not registry.is_available(a.id):
            continue
        if not registry.agent_supports(a.id, WORKFLOW_CAPABILITY):
            continue
        running = await _active_runs(db, a.id)
        if running >= a.max_concurrent_runs:
            continue
        out.append((running, a.id, a))
    return [a for _, _, a in sorted(out, key=lambda t: (t[0], str(t[1])))]


async def _active_runs(db: AsyncSession, agent_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count()).select_from(AgentRun).where(AgentRun.agent_id == agent_id,
                                                         AgentRun.status.in_(ACTIVE_STATUSES))
    )


async def _claim_slot(db: AsyncSession, found: list[Agent]) -> Agent | None:
    """The first candidate that still has a free slot once its row is locked: a concurrent pass for another
    question waits here until this one commits, then counts the run this one queued."""
    for a in found:
        # NO KEY UPDATE: route passes queue behind each other, run inserts (a key share on the agent) do not
        await db.execute(select(Agent.id).where(Agent.id == a.id).with_for_update(key_share=True))
        if await _active_runs(db, a.id) < a.max_concurrent_runs:
            return a
    return None


async def _untried_bound(db: AsyncSession, q: Question) -> bool:
    """Is any agent bound to the project, whatever its state, still untried for this question?"""
    tried = {uuid.UUID(t) for t in q.tried_agent_ids or []}
    ids = (
        await db.execute(
            select(Agent.id)
            .join(AgentBinding, AgentBinding.agent_id == Agent.id)
            .where(AgentBinding.project_id == q.target_project_id, owner_can_access(q.target_project_id))
        )
    ).scalars().all()
    return any(i not in tried for i in ids)


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
    agent = await _claim_slot(db, found)
    if agent is None:
        if q.tried_agent_ids and not await _untried_bound(db, q):
            # every agent that could answer has tried (or had a draft rejected): ask a human (A2A-5)
            q.status = QuestionStatus.needs_human
            await db.flush()
            from app.a2a.service import notify, notify_waiting

            await notify(db, q)
            await notify_waiting(db, q)
        return None  # otherwise it waits for a runner
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


async def release_stale(db: AsyncSession) -> None:
    """Answering runs queued for a while on an agent that is not available (its runner went away before the
    run was sent) are cancelled, so their question moves on to another agent (A2A-5)."""
    from app.agent_runs.service import (  # local: the run service imports this module
        _lock_run,
        _transition,
    )

    cutoff = func.now() - timedelta(seconds=STALE_QUEUED_SECONDS)
    rows = (
        await db.execute(
            select(AgentRun.id, AgentRun.question_id, AgentRun.agent_id, Agent.owner_id)
            .join(Agent, Agent.id == AgentRun.agent_id)
            .where(AgentRun.question_id.is_not(None), AgentRun.status == RunStatus.queued,
                   AgentRun.created_at < cutoff)
            .order_by(AgentRun.created_at)
        )
    ).all()
    for run_id, question_id, agent_id, owner_id in rows:
        if registry.is_available(agent_id):
            continue
        # the question before the run: the order of a human answer or a withdrawal
        await db.execute(select(Question.id).where(Question.id == question_id).with_for_update())
        run = await _lock_run(db, run_id)
        if run is not None and run.status == RunStatus.queued:
            await _transition(db, run, RunStatus.cancelled, "agent_run_cancelled", owner_id=owner_id,
                              reason="agent_unavailable")


async def route_and_dispatch() -> None:
    """The loop's pass: give up stale runs, route queued questions, and send queued answering runs to every
    connected owner (a run left queued when its send failed, or routed where nobody dispatched it)."""
    from app.agent_runs.service import dispatch_pending
    from app.workflow import engine  # local: the engine imports the run service

    async with SessionLocal() as db:
        await release_stale(db)
        await route_queued(db)
        await engine.dispatch_queued(db)
        await db.commit()
        owners = (
            await db.execute(
                select(Agent.owner_id).join(AgentRun, AgentRun.agent_id == Agent.id)
                .where(AgentRun.question_id.is_not(None), AgentRun.status == RunStatus.queued).distinct()
            )
        ).scalars().all()
    for owner_id in sorted(owners):
        if not registry.conns_for_user(owner_id):
            continue
        async with SessionLocal() as s:
            await dispatch_pending(s, owner_id)
            await s.commit()


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
    if q is None:
        return
    from app.workflow.engine import (
        _git_changed,  # local: the engine imports the run service
    )

    if _git_changed(run):
        # R1: a read-only answering session changed the repository; its draft is not to be trusted
        await audit.record(db, "a2a.answer.enforcement_violation", actor_id=None, target_type="question",
                           target_id=q.id, data={"run_id": str(run.id), "agent_id": str(run.agent_id)})
        if q.status == QuestionStatus.draft and q.draft_agent_id == run.agent_id:
            q.draft_md, q.draft_citations, q.draft_agent_id = None, [], None
            q.redacted = False
            q.status = QuestionStatus.routed  # unanswered: retried below like a run that gave no answer
    if q.status != QuestionStatus.routed:
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
    from app.a2a.service import notify, notify_waiting

    await notify(db, q)
    if q.status == QuestionStatus.needs_human:
        await notify_waiting(db, q)
    if q.status == QuestionStatus.queued:
        await route_question(db, q.id)

