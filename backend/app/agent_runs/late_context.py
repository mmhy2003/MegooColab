"""The Knowledge Base and Memory sections of a queued workflow run's prompt, added after the commit that queued it
(MC-215).

`enqueue` builds the prompt from DB reads only, under the task, workflow and run locks, and marks where these
sections go (`AgentRun.context_at`). Their providers may wait seconds on an AI provider, so they run here, from
`dispatch_pending`, with no row lock held. The run is never claimed while it is marked (`_claim_next`)."""

import logging
import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.core.db import SessionLocal
from app.tasks.models import Task
from app.workflow import context as wf_context
from app.workflow.models import RunRole

log = logging.getLogger(__name__)


def insert_sections(prompt: str, at: int, sections: list[str]) -> str:
    """`sections` placed at `at`, each after a blank line, in order, while the prompt stays within
    MAX_PROMPT_CHARS: a section that does not fit is left out, and so are those after it."""
    room = wf_context.MAX_PROMPT_CHARS - len(prompt)
    added = ""
    for section in sections:
        part = "\n\n" + section
        if len(added) + len(part) > room:
            break
        added += part
    return prompt[:at] + added + prompt[at:]


async def _fill(run_id: uuid.UUID) -> None:
    async with SessionLocal() as s:  # reads only: no row lock is held while the providers wait
        run = await s.get(AgentRun, run_id)
        if run is None or run.status != RunStatus.queued or run.context_at is None:
            return
        task = await s.get(Task, run.task_id)
        if task is None:
            return
        sections = await wf_context.late_sections(s, task, RunRole(run.workflow_role))
        prompt = insert_sections(run.prompt, run.context_at, sections)
        # the run row alone, for one statement (lock 3 of the engine's order); a run cancelled meanwhile, or
        # filled by another dispatch, matches nothing
        await s.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.status == RunStatus.queued, AgentRun.context_at.is_not(None))
            .values(prompt=prompt, context_at=None)
        )
        await s.commit()


async def _clear(run_id: uuid.UUID) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(AgentRun).where(AgentRun.id == run_id, AgentRun.context_at.is_not(None)).values(context_at=None)
        )
        await s.commit()


async def fill_pending(owner_id: uuid.UUID) -> None:
    """Add the late sections to each queued run of the owner's agents that waits for them, oldest first. Never
    raises: a run whose fill fails has its mark cleared and goes without them, as optional context must never
    hold a run back."""
    try:
        async with SessionLocal() as s:
            run_ids = list((await s.execute(
                select(AgentRun.id)
                .join(Agent, Agent.id == AgentRun.agent_id)
                .where(Agent.owner_id == owner_id, AgentRun.status == RunStatus.queued,
                       AgentRun.context_at.is_not(None))
                .order_by(AgentRun.created_at, AgentRun.id)
            )).scalars())
    except Exception:
        log.exception("late context: listing the queued runs of owner %s failed", owner_id)
        return
    for run_id in run_ids:
        try:
            await _fill(run_id)
        except Exception:
            log.exception("late context: filling run %s failed; it goes without its sections", run_id)
            try:
                await _clear(run_id)
            except Exception:
                log.exception("late context: clearing the mark of run %s failed", run_id)
