"""Review and Done stages (WF-5, WF-6a, WF-6b).

Review (entered from build.enter_review, round 1):
  final_review (fresh)
    approved           -> Done
    changes_requested  -> round 1: final_fix (fresh, with the findings), and when it ends, final_review round 2
                          (it sees round 1's findings); round 2: escalation final_review_not_clean
                          (`accept` enters Done)
    no verdict         -> one nudge, then escalation review_incomplete
  final_fix has no completion tool: its run simply ends. A failed one falls under the normal retries.

Done:
  finish (fresh) states the effective finishing option and ends with report_finish.
    reported and tests_passed -> human code review required: wait on human_code_review; else finished
    otherwise                 -> one nudge, then escalation finish_incomplete

`wf.review_round` is the final review's round (build.enter_review sets 1; the final_fix handler sets 2).
"""

import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun
from app.audit import service as audit
from app.auth.models import User
from app.core.text import strip_nul
from app.kb import filing
from app.projects.models import ColumnCategory, Project
from app.tasks.models import Task
from app.workflow import build, engine, questions
from app.workflow.models import (
    Driver,
    FinishingOption,
    Needs,
    ReviewScope,
    RunRole,
    Stage,
    StepReview,
    TaskWorkflow,
    Verdict,
    WorkflowStatus,
)

MAX_BRANCH = 200
MAX_PR_URL = 500

FINISH_NUDGE = "Re-verify the tests, perform the finishing option, then call report_finish."
OUTCOME_OF = {
    FinishingOption.merge_local: "merged_local",
    FinishingOption.pull_request: "pr_opened",
    FinishingOption.keep_branch: "branch_kept",
}


def _422(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


# ---- Review ----------------------------------------------------------------------------------


async def _handle_final_review(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    requester_id = await engine.owner_id(db, run)
    review = (
        await db.execute(select(StepReview).where(StepReview.run_id == run.id).limit(1))
    ).scalar_one_or_none()
    if review is None:
        if not wf.nudged:
            wf.nudged = True
            await engine.rerun(
                db, wf, task, last=run, requested_by=requester_id, resume_kind="nudge", payload=build.REVIEW_NUDGE
            )
        else:
            await engine.escalate(db, wf, "review_incomplete")
        return
    if review.verdict == Verdict.approved:
        owner = await db.get(User, requester_id)
        await filing.file_final_review(db, task, review, summary=f"Final review round {review.round}: approved",
                                       actor=owner)
        await enter_done(db, wf, task, requested_by=requester_id)
    elif review.round < 2:
        wf.nudged = False
        await engine.enqueue(db, wf, task, RunRole.final_fix, requested_by=requester_id)
    else:
        await engine.escalate(db, wf, "final_review_not_clean")


async def _asked_or_answered(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> bool:
    """final_fix and finish may ask a human: wait for the answer, or resume the run's session with an answer
    that arrived while it was running. True when the run's end was handled that way."""
    if await questions.has_open_question(db, run.id):
        engine.wait_for(wf, Needs.question)
        return True
    pending = await questions.undelivered_answer(db, task.id, run.id)
    if pending is not None:
        await questions.deliver(db, wf, task, pending, requested_by=await engine.owner_id(db, run))
        return True
    return False


async def _handle_final_fix(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    """The fix round ended: the scoped re-review (round 2) follows."""
    if await _asked_or_answered(db, wf, task, run):
        return
    wf.review_round = 2
    wf.nudged = False
    await engine.enqueue(db, wf, task, RunRole.final_review, requested_by=await engine.owner_id(db, run))


async def _accept_final_review(db: AsyncSession, wf: TaskWorkflow, task: Task, user: User) -> None:
    """Escalation `accept` after the re-review: the human passes the final review."""
    review = (
        await db.execute(
            select(StepReview)
            .where(StepReview.task_id == task.id, StepReview.scope == ReviewScope.final)
            .order_by(StepReview.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if review is not None:
        await filing.file_final_review(db, task, review, summary=f"Accepted by {user.name}", actor=user)
    await enter_done(db, wf, task, requested_by=user.id)


# ---- Done ------------------------------------------------------------------------------------


async def enter_done(db: AsyncSession, wf: TaskWorkflow, task: Task, *, requested_by: uuid.UUID) -> None:
    """The Done stage: the finish run states the effective option. The card moves when the workflow finishes."""
    await engine.set_stage(db, wf, task, Stage.done)
    project = await db.get(Project, task.project_id)
    # Frozen for the whole Done stage, so a project setting changed meanwhile cannot change this run. The task's
    # override is overwritten on purpose: set_finishing is refused from here on, so it has served its purpose.
    wf.finishing_override = engine.finishing_option(project, wf)
    wf.finish_requires_human_review = bool(project.require_human_code_review)
    wf.review_round = 0
    wf.nudged = False
    await engine.enqueue(db, wf, task, RunRole.finish, requested_by=requested_by)


async def finish_workflow(db: AsyncSession, wf: TaskWorkflow, task: Task, actor_id: uuid.UUID | None) -> None:
    wf.status = WorkflowStatus.finished
    wf.needs = None
    wf.finished_at = datetime.now(UTC)
    await engine.move_to_category(db, task, ColumnCategory.done)
    await engine.record_workflow_event(db, task, actor_id, "workflow.finished", {
        "outcome": wf.finish_outcome, "branch": wf.branch, "pr_url": wf.pr_url,
    })


async def report_finish(
    db: AsyncSession, run: AgentRun, outcome: str, branch: str, pr_url: str | None, tests_passed: bool
) -> None:
    """A finish run reports how it finished (MCP tool in Task 11). A later report from the same run replaces it.
    The caller commits."""
    wf, task = await build.lock_run_role(db, run, (RunRole.finish,))
    project = await db.get(Project, task.project_id)
    option = engine.finishing_option(project, wf)
    if outcome != OUTCOME_OF[option]:
        raise _422("wrong_finish")
    if not isinstance(tests_passed, bool) or not isinstance(branch, str) or (
        pr_url is not None and not isinstance(pr_url, str)
    ):
        raise _422("invalid_finish_result")
    branch = strip_nul(branch)
    if len(branch) > MAX_BRANCH:
        raise _422("too_large")
    if option == FinishingOption.pull_request:
        pr_url = strip_nul(pr_url or "").strip()
        if not pr_url:
            raise _422("pr_url_required")
        if len(pr_url) > MAX_PR_URL:
            raise _422("too_large")
        parts = urlsplit(pr_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise _422("invalid_pr_url")
    else:
        pr_url = None
    run.step_result = {"outcome": outcome, "branch": branch, "pr_url": pr_url, "tests_passed": tests_passed}
    wf.branch, wf.pr_url, wf.finish_outcome = branch or None, pr_url, outcome
    await engine.record_workflow_event(db, task, None, "finish.reported", {
        "outcome": outcome, "branch": branch, "pr_url": pr_url, "tests_passed": tests_passed,
    })


async def _handle_finish(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    if await _asked_or_answered(db, wf, task, run):
        return
    if (run.step_result or {}).get("tests_passed") is True:
        project = await db.get(Project, task.project_id)
        if engine.requires_human_review(project, wf) and engine.finishing_option(project, wf) == FinishingOption.pull_request:
            engine.wait_for(wf, Needs.human_code_review)
        else:
            await finish_workflow(db, wf, task, None)
        return
    if not wf.nudged:
        wf.nudged = True
        await engine.rerun(
            db, wf, task, last=run, requested_by=await engine.owner_id(db, run), resume_kind="nudge",
            payload=FINISH_NUDGE,
        )
    else:
        await engine.escalate(db, wf, "finish_incomplete")


# ---- human decisions (WF-6) -------------------------------------------------------------------


async def approve_human_review(db: AsyncSession, user: User, task: Task) -> TaskWorkflow:
    """A human clicked "PR approved": the workflow finishes. The first approval wins."""
    wf = await engine.lock_task(db, task)
    await engine.require_actor(db, user, task, wf)
    needed_review = wf is not None and wf.finish_requires_human_review is True
    if needed_review and wf.status == WorkflowStatus.finished:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_decided")
    if wf is None or wf.status != WorkflowStatus.waiting_human or wf.needs != Needs.human_code_review:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_waiting_for_decision")
    await engine.record_workflow_event(db, task, user.id, "human_review.approved", {"pr_url": wf.pr_url})
    await audit.record(
        db, "workflow.human_review_approved", actor_id=user.id, target_type="task", target_id=task.id,
        data={"pr_url": wf.pr_url},
    )
    await finish_workflow(db, wf, task, user.id)
    return wf


async def set_finishing(db: AsyncSession, user: User, task: Task, option: FinishingOption | None) -> TaskWorkflow:
    """The task-level override of the project's finishing option, allowed until the Done stage."""
    wf = await engine.lock_task(db, task)  # never creates one: an idle row would block human board moves
    await engine.require_actor(db, user, task, wf)
    if wf is None or wf.driver != Driver.runner or wf.status == WorkflowStatus.idle:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_not_started")
    if wf.stage == Stage.done:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_past_finishing")
    wf.finishing_override = option
    await engine.record_workflow_event(
        db, task, user.id, "finishing.changed", {"option": option.value if option else None}
    )
    return wf


engine.ROLE_HANDLERS[RunRole.final_review] = _handle_final_review
engine.ROLE_HANDLERS[RunRole.final_fix] = _handle_final_fix
engine.ROLE_HANDLERS[RunRole.finish] = _handle_finish
engine.ACCEPT_HANDLERS["final_review_not_clean"] = _accept_final_review
