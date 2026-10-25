"""Build stage: the approved plan's steps, each implemented, then reviewed by a fresh reviewer (WF-5, AGT-14).

Per step n:
  implement (session "implement:n", fresh) -> complete_step(tests_passed) -> step_review (fresh, round r)
    approved           -> the step's subtask moves to done; step n+1 starts, or after the last step, Review
    changes_requested  -> r < 3: step_fix resumes "implement:n" with the findings, then round r+1
                          r = 3: escalation review_rounds_exhausted (`accept` approves the step)

Bookkeeping on the workflow:
  - `review_round` is the round of the current step's latest review: +1 when a step_review is queued (a retry
    or nudge of that review keeps it), 0 again when a step is approved.
  - `nudged` allows one nudge per expected output: reset whenever the step moves on (review queued, fix
    queued, step approved).
  - `sessions["base:<n>"]` is the HEAD step n started from: the git_before of its first implement run that
    reported one. It is a cache (a reassignment clears `sessions`; it is then read from the runs again) for the
    `step.no_commit` warning.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun
from app.auth.models import User
from app.core.text import strip_nul
from app.projects.models import ColumnCategory
from app.tasks.models import Task
from app.workflow import engine, questions
from app.workflow.models import (
    DocKind,
    DocStatus,
    Needs,
    ReviewScope,
    RunRole,
    Stage,
    StepReview,
    TaskWorkflow,
    Verdict,
    WorkflowDocument,
    WorkflowStatus,
)

MAX_REVIEW_ROUNDS = 3
MAX_SUMMARY = 2_000
MAX_TEST_COMMAND = 200
MAX_FINDINGS = 50
MAX_FINDING_FILE = 300
MAX_FINDING_SUMMARY = 1_000
SEVERITIES = ("critical", "important", "minor")

WORK_NUDGE = "Call complete_step after the step's tests pass, or ask_human if you are blocked."
REVIEW_NUDGE = "Call submit_review with your verdict and findings."

WORK_ROLES = (RunRole.implement, RunRole.step_fix)
REVIEW_ROLES = (RunRole.step_review, RunRole.final_review)


def _422(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


async def lock_run_role(db: AsyncSession, run: AgentRun, roles: tuple[RunRole, ...]) -> tuple[TaskWorkflow, Task]:
    """The workflow lock first (as every engine entry point), then the run's role."""
    task = await db.get(Task, run.task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task_not_found")
    wf = await engine.lock_task(db, task)
    if run.workflow_role is None or RunRole(run.workflow_role) not in roles:
        raise _422("not_allowed_in_role")
    if wf is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_not_active")
    return wf, task


# ---- agent outputs (MCP tools in Task 11) ------------------------------------------------


async def complete_step(
    db: AsyncSession, run: AgentRun, step: int, summary: str, tests_passed: bool, test_command: str | None
) -> None:
    """An implement or step_fix run reports its step done. A later report from the same run replaces it.
    The caller commits."""
    _, task = await lock_run_role(db, run, WORK_ROLES)
    if isinstance(step, bool) or not isinstance(step, int) or step != run.step:
        raise _422("wrong_step")
    run.step_result = _clean_step_result(summary, tests_passed, test_command)
    await engine.record_workflow_event(db, task, None, "step.completed", {"step": step, "tests_passed": tests_passed})


def _clean_step_result(summary: str, tests_passed: bool, test_command: str | None) -> dict:
    if not isinstance(tests_passed, bool):
        raise _422("invalid_step_result")
    if not isinstance(summary, str) or (test_command is not None and not isinstance(test_command, str)):
        raise _422("invalid_step_result")
    summary = strip_nul(summary)
    test_command = (strip_nul(test_command) or None) if test_command is not None else None
    if len(summary) > MAX_SUMMARY or (test_command and len(test_command) > MAX_TEST_COMMAND):
        raise _422("too_large")
    return {"summary": summary, "tests_passed": tests_passed, "test_command": test_command}


async def complete_step_connect_only(
    db: AsyncSession, wf: TaskWorkflow, task: Task, step: int, summary: str, tests_passed: bool,
    test_command: str | None,
) -> None:
    """AGT-32: a connect-only agent reports the current step done. There are no review runs: passing tests
    complete the step (its subtask moves to done) and the next one begins; after the last step the workflow
    finishes and the card moves to done. Failing tests are recorded and the step stays. The caller holds the
    workflow lock (engine.lock_connect_only) and commits."""
    if wf.status == WorkflowStatus.finished:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_finished")
    if wf.stage != Stage.build:
        raise HTTPException(status.HTTP_409_CONFLICT, "wrong_stage")
    if isinstance(step, bool) or not isinstance(step, int) or step != wf.current_step:
        raise _422("wrong_step")
    _clean_step_result(summary, tests_passed, test_command)
    await engine.record_workflow_event(db, task, None, "step.completed", {"step": step, "tests_passed": tests_passed})
    if not tests_passed:
        return
    steps = await _plan_steps(db, task.id)
    await _done_subtask(db, steps, step)
    if step < len(steps):
        engine.set_step(wf, step + 1)
        return
    from app.workflow import finish  # local: finish imports this module

    await engine.set_stage(db, wf, task, Stage.done)
    await finish.finish_workflow(db, wf, task, None)


def _clean_findings(findings) -> list[dict]:
    if not isinstance(findings, list):
        raise _422("invalid_finding")
    if len(findings) > MAX_FINDINGS:
        raise _422("too_many_findings")
    out = []
    for f in findings:
        if not isinstance(f, dict) or f.get("severity") not in SEVERITIES:
            raise _422("invalid_finding")
        file, line, summary = f.get("file"), f.get("line"), f.get("summary")
        if file is not None and not isinstance(file, str):
            raise _422("invalid_finding")
        if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
            raise _422("invalid_finding")
        if not isinstance(summary, str):
            raise _422("invalid_finding")
        file = (strip_nul(file).strip() or None) if file is not None else None
        summary = strip_nul(summary).strip()
        if not summary:
            raise _422("invalid_finding")
        if (file and len(file) > MAX_FINDING_FILE) or len(summary) > MAX_FINDING_SUMMARY:
            raise _422("too_large")
        out.append({"severity": f["severity"], "file": file, "line": line, "summary": summary})
    return out


async def submit_review(db: AsyncSession, run: AgentRun, verdict: str, findings: list[dict]) -> StepReview:
    """A step_review or final_review run gives its verdict, once (409 already_submitted). The caller commits."""
    wf, task = await lock_run_role(db, run, REVIEW_ROLES)
    try:
        verdict = Verdict(verdict)
    except ValueError:
        raise _422("invalid_verdict") from None
    clean = _clean_findings(findings)
    if await db.scalar(select(StepReview.id).where(StepReview.run_id == run.id).limit(1)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_submitted")
    scope = ReviewScope.step if RunRole(run.workflow_role) == RunRole.step_review else ReviewScope.final
    review = StepReview(
        task_id=task.id, run_id=run.id, scope=scope, step=run.step if scope == ReviewScope.step else None,
        round=max(wf.review_round, 1), verdict=verdict, findings=clean,
    )
    db.add(review)
    await db.flush()
    await engine.record_workflow_event(db, task, None, "review.result", {
        "scope": scope.value, "step": review.step, "round": review.round, "verdict": verdict.value,
        "counts": {sev: sum(f["severity"] == sev for f in clean) for sev in SEVERITIES},
        "review_id": str(review.id),
    })
    return review


# ---- run outcomes --------------------------------------------------------------------------


async def _plan_steps(db: AsyncSession, task_id: uuid.UUID) -> list[dict]:
    steps = await db.scalar(
        select(WorkflowDocument.steps)
        .where(
            WorkflowDocument.task_id == task_id,
            WorkflowDocument.kind == DocKind.plan,
            WorkflowDocument.status == DocStatus.approved,
        )
        .order_by(WorkflowDocument.version.desc())
        .limit(1)
    )
    return list(steps or [])


async def _step_base(db: AsyncSession, wf: TaskWorkflow, n: int) -> str | None:
    key = f"base:{n}"
    if key not in wf.sessions:
        stmt = select(AgentRun.git_before["head"].astext).where(
            AgentRun.task_id == wf.task_id,
            AgentRun.workflow_role == RunRole.implement,
            AgentRun.step == n,
            AgentRun.git_before.is_not(None),
        )
        if wf.started_at is not None:
            stmt = stmt.where(AgentRun.created_at >= wf.started_at)
        head = await db.scalar(stmt.order_by(AgentRun.created_at, AgentRun.id).limit(1))
        if head:
            wf.sessions[key] = head
    return wf.sessions.get(key)


async def _warn_if_no_commit(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    """A step reported complete whose HEAD never moved since the step started: a warning, not a block."""
    head = (run.git_after or {}).get("head")
    base = await _step_base(db, wf, run.step)
    if head and base and head == base:
        await engine.record_workflow_event(db, task, None, "step.no_commit", {"step": run.step})


async def _queue_review(db: AsyncSession, wf: TaskWorkflow, task: Task, n: int, requested_by: uuid.UUID) -> None:
    wf.review_round += 1
    wf.nudged = False
    await engine.enqueue(db, wf, task, RunRole.step_review, step=n, requested_by=requested_by)


async def _handle_work(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    """implement / step_fix ended: a question waits for its answer; a completed step with passing tests goes
    to review; otherwise one nudge, then the escalation step_incomplete."""
    if await questions.has_open_question(db, run.id):
        engine.wait_for(wf, Needs.question)
        return
    owner_id = await engine.owner_id(db, run)
    if (run.step_result or {}).get("tests_passed") is True:
        await _warn_if_no_commit(db, wf, task, run)
        await _queue_review(db, wf, task, run.step, owner_id)
        return
    pending =await questions.undelivered_answer(db, task.id, run.id)
    if pending is not None:  # answered while this run was still running: it gets the answer, not a nudge
        await questions.deliver(db, wf, task, pending, requested_by=owner_id)
        return
    if not wf.nudged:
        wf.nudged = True
        await engine.rerun(db, wf, task, last=run, requested_by=owner_id, resume_kind="nudge", payload=WORK_NUDGE)
        return
    await engine.escalate(db, wf, "step_incomplete")


async def _handle_step_review(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    """step_review ended: approve and advance, request a fix round, or escalate after round 3. Without a
    verdict: one nudge, then the escalation review_incomplete."""
    owner_id = await engine.owner_id(db, run)
    review = (
        await db.execute(select(StepReview).where(StepReview.run_id == run.id).limit(1))
    ).scalar_one_or_none()
    if review is None:
        if not wf.nudged:
            wf.nudged = True
            await engine.rerun(
                db, wf, task, last=run, requested_by=owner_id, resume_kind="nudge", payload=REVIEW_NUDGE
            )
        else:
            await engine.escalate(db, wf, "review_incomplete")
        return
    if review.verdict == Verdict.approved:
        await approve_step(db, wf, task, run.step, requested_by=owner_id)
    elif review.round < MAX_REVIEW_ROUNDS:
        wf.nudged = False
        await engine.enqueue(
            db, wf, task, RunRole.step_fix, step=run.step, resume_kind="findings", payload=list(review.findings),
            requested_by=owner_id,
        )
    else:
        await engine.escalate(db, wf, "review_rounds_exhausted")


async def _done_subtask(db: AsyncSession, steps: list[dict], n: int) -> None:
    """Move step n's subtask to the first done column, unless a human deleted it (it may be mid-delete: its row
    is locked first, and a row gone by then is skipped)."""
    sub_id = steps[n - 1].get("subtask_id") if 1 <= n <= len(steps) else None
    if not sub_id:
        return
    sub = (
        await db.execute(
            select(Task)
            .where(Task.id == uuid.UUID(sub_id))
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if sub is not None:
        await engine.move_to_category(db, sub, ColumnCategory.done)


async def approve_step(db: AsyncSession, wf: TaskWorkflow, task: Task, n: int, *, requested_by: uuid.UUID) -> None:
    """Step n passed: its subtask is done, and the next step (fresh) or the Review stage starts."""
    steps = await _plan_steps(db, task.id)
    await _done_subtask(db, steps, n)
    await engine.record_workflow_event(db, task, None, "step.approved", {"step": n})
    await questions.retire_answers(db, task.id)  # an answer meant for step n can no longer be delivered
    wf.review_round = 0
    wf.nudged = False
    wf.failures = 0
    if n < len(steps):
        engine.set_step(wf, n + 1)
        await engine.enqueue(db, wf, task, RunRole.implement, step=n + 1, requested_by=requested_by)
    else:
        await enter_review(db, wf, task, requested_by=requested_by)


async def enter_review(db: AsyncSession, wf: TaskWorkflow, task: Task, *, requested_by: uuid.UUID) -> None:
    """The Review stage with a fresh final review (round 1); finish.py handles its outcome."""
    await engine.set_stage(db, wf, task, Stage.review)
    await engine.move_to_category(db, task, ColumnCategory.review)
    wf.review_round = 1  # the final review's first round
    await engine.enqueue(db, wf, task, RunRole.final_review, requested_by=requested_by)


async def _accept_review_rounds(db: AsyncSession, wf: TaskWorkflow, task: Task, user: User) -> None:
    """Escalation `accept` after 3 review rounds: the human passes the step."""
    await approve_step(db, wf, task, wf.current_step, requested_by=user.id)


engine.ROLE_HANDLERS[RunRole.implement] = _handle_work
engine.ROLE_HANDLERS[RunRole.step_fix] = _handle_work
engine.ROLE_HANDLERS[RunRole.step_review] = _handle_step_review
engine.ACCEPT_HANDLERS["review_rounds_exhausted"] = _accept_review_rounds
