"""Decision and test-run records: what an agent decided on its own, and what its tests said.

Agents post them through `record_decision` and `record_tests` (MCP). They are shown on the task, judged by the
step and final reviewers, and a run's decisions feed the memory. Only the text an agent posts is stored: a
test run carries its command, counts and failing test names, never output (NFR-2).
"""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun
from app.agents.models import Agent
from app.auth.models import User
from app.core.events import Event, publish
from app.core.text import strip_nul
from app.tasks.models import Task, TaskEvent
from app.workflow import engine
from app.workflow.models import Stage, TaskWorkflow, WorkflowDecision, WorkflowTestRun
from app.workflow.schemas import DecisionOut, RecordsOut, TestRunOut

MAX_TEXT = 1000
MAX_COST = 500
MAX_COMMAND = 200
MAX_FAILING = 20
MAX_FAILING_NAME = 300
MAX_DECISIONS_PER_STEP = 30
MAX_TEST_RUNS_PER_STEP = 50
EVENT_DECISION_CHARS = 140


def _422(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


def _text(value: Any, limit: int, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise _422("invalid_record")
    value = strip_nul(value).strip()
    if not value:
        if required:
            raise _422("invalid_record")
        return None
    if len(value) > limit:
        raise _422("too_large")
    return value


def _count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _422("invalid_record")
    return value


def _failing(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_FAILING:
        raise _422("invalid_record")
    return [_text(name, MAX_FAILING_NAME) for name in value]


def _where(run: AgentRun | None, wf: TaskWorkflow) -> tuple[Stage, int | None]:
    if run is not None:
        return Stage(run.stage), run.step
    return Stage(wf.stage), wf.current_step


async def _room(db: AsyncSession, model, task: Task, stage: Stage, step: int | None, cap: int) -> None:
    """At most `cap` records per (task, stage, step); the caller holds the workflow lock."""
    same_step = model.step.is_(None) if step is None else model.step == step
    count = await db.scalar(
        select(func.count()).select_from(model).where(model.task_id == task.id, model.stage == stage, same_step)
    )
    if count >= cap:
        raise _422("too_many_records")


async def record_decision(
    db: AsyncSession, task: Task, wf: TaskWorkflow, *, run: AgentRun | None, posted_by: uuid.UUID | None,
    decision: Any, reason: Any, cost_if_wrong: Any, plan_said: Any = None,
) -> WorkflowDecision:
    """Store a decision. The caller holds the workflow lock (and the run, for a run token) and commits."""
    clean = {
        "decision": _text(decision, MAX_TEXT),
        "reason": _text(reason, MAX_TEXT),
        "cost_if_wrong": _text(cost_if_wrong, MAX_COST),
        "plan_said": _text(plan_said, MAX_TEXT, required=False),
    }
    stage, step = _where(run, wf)
    await _room(db, WorkflowDecision, task, stage, step, MAX_DECISIONS_PER_STEP)
    row = WorkflowDecision(
        task_id=task.id, run_id=run.id if run else None, agent_id=run.agent_id if run else None,
        posted_by=None if run else posted_by, stage=stage, step=step, created_at=func.clock_timestamp(), **clean,
    )
    db.add(row)
    await db.flush()
    await engine.record_workflow_event(db, task, None, "decision.recorded", {
        "step": step, "stage": stage.value, "decision": clean["decision"][:EVENT_DECISION_CHARS],
    })
    return row


async def record_tests(
    db: AsyncSession, task: Task, wf: TaskWorkflow, *, run: AgentRun | None, posted_by: uuid.UUID | None,
    command: Any, passed: Any, total: Any = None, failed: Any = None, skipped: Any = None, failing: Any = None,
) -> WorkflowTestRun:
    """Store a test run. No activity entry (they are frequent): viewers are refreshed through task.updated."""
    if not isinstance(passed, bool):
        raise _422("invalid_record")
    clean = {
        "command": _text(command, MAX_COMMAND), "passed": passed, "total": _count(total), "failed": _count(failed),
        "skipped": _count(skipped), "failing": _failing(failing),
    }
    stage, step = _where(run, wf)
    await _room(db, WorkflowTestRun, task, stage, step, MAX_TEST_RUNS_PER_STEP)
    row = WorkflowTestRun(
        task_id=task.id, run_id=run.id if run else None, agent_id=run.agent_id if run else None,
        posted_by=None if run else posted_by, stage=stage, step=step, created_at=func.clock_timestamp(), **clean,
    )
    db.add(row)
    await db.flush()
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
    return row


async def _authors(db: AsyncSession, rows: list) -> dict[uuid.UUID, str]:
    """Row id -> the agent's name, or "<person>'s connected agent" for a connect-only record."""
    agent_ids = {r.agent_id for r in rows if r.agent_id}
    user_ids = {r.posted_by for r in rows if r.posted_by}
    agents = dict((await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))).all()) if agent_ids else {}
    users = dict((await db.execute(select(User.id, User.name).where(User.id.in_(user_ids)))).all()) if user_ids else {}
    out = {}
    for r in rows:
        if r.agent_id in agents:
            out[r.id] = agents[r.agent_id]
        elif r.posted_by in users:
            out[r.id] = f"{users[r.posted_by]}'s connected agent"
        else:
            out[r.id] = "An agent"
    return out


async def _all(db: AsyncSession, model, task_id: uuid.UUID) -> list:
    stmt = select(model).where(model.task_id == task_id).order_by(model.created_at, model.id)
    return list((await db.execute(stmt)).scalars())


async def unverified_steps(db: AsyncSession, task_id: uuid.UUID) -> list[int]:
    """Steps whose latest `step.completed` claims passing tests with no passing test run recorded for that step
    since the claim before it (or ever, for a first claim)."""
    claims = (
        await db.execute(
            select(TaskEvent.data, TaskEvent.created_at)
            .where(TaskEvent.task_id == task_id, TaskEvent.kind == "step.completed")
            .order_by(TaskEvent.created_at, TaskEvent.id)
        )
    ).all()
    passing = (
        await db.execute(
            select(WorkflowTestRun.step, WorkflowTestRun.created_at)
            .where(WorkflowTestRun.task_id == task_id, WorkflowTestRun.passed.is_(True),
                   WorkflowTestRun.stage == Stage.build)
        )
    ).all()
    by_step: dict[int, list] = {}
    for data, at in claims:
        step = data.get("step") if isinstance(data, dict) else None
        if isinstance(step, int) and not isinstance(step, bool):
            by_step.setdefault(step, []).append((data.get("tests_passed") is True, at))
    out = []
    for step, history in sorted(by_step.items()):
        claimed, at = history[-1]
        since = history[-2][1] if len(history) > 1 else None
        if claimed and not any(s == step and (since is None or t > since) and t <= at for s, t in passing):
            out.append(step)
    return out


async def task_records(db: AsyncSession, task_id: uuid.UUID) -> RecordsOut:
    decisions = await _all(db, WorkflowDecision, task_id)
    runs = await _all(db, WorkflowTestRun, task_id)
    authors = await _authors(db, [*decisions, *runs])
    return RecordsOut(
        decisions=[
            DecisionOut(
                id=d.id, stage=d.stage, step=d.step, decision=d.decision, reason=d.reason,
                cost_if_wrong=d.cost_if_wrong, plan_said=d.plan_said, author=authors[d.id], created_at=d.created_at,
            )
            for d in decisions
        ],
        test_runs=[
            TestRunOut(
                id=t.id, stage=t.stage, step=t.step, command=t.command, passed=t.passed, total=t.total,
                failed=t.failed, skipped=t.skipped, failing=list(t.failing or []), author=authors[t.id],
                created_at=t.created_at,
            )
            for t in runs
        ],
        unverified_steps=await unverified_steps(db, task_id),
    )
