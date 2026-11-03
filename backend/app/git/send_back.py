"""Changes requested on the task's pull request send the task back to its agent (piece 3). A "changes requested"
review, or a comment starting with /fix, on the pull request the workflow waits on, with the project's checkbox on:
the agent gets a fix run that pushes to the same branch. At most MAX_PR_FIX_ROUNDS per pull request; beyond that
the human decides."""

import re
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.projects.models import Project
from app.tasks.models import Task

MAX_PR_FIX_ROUNDS = 3
MAX_SUMMARY = 2000
PR_FIX_NUDGE = "Fix what was asked on the pull request, run the tests, push to the same branch, then call report_pr_fix."
# GitHub says how the author relates to the repository; only people who can write to it may send a task back
WRITE_ACCESS = ("OWNER", "MEMBER", "COLLABORATOR")
_FIX = re.compile(r"^\s*/fix(?:\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class Trigger:
    kind: str  # "review" | "fix_comment"
    pr_url: str | None
    pr_number: int | None
    by: str  # the actor's name (agent or person)
    excerpt: str
    where: str | None  # "src/a.py:88" from the review's first line comment, when known
    association: str | None
    host: str  # GitKind value


def is_fix_comment(text: object) -> bool:
    return isinstance(text, str) and _FIX.match(text) is not None


def _same(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.rstrip("/").lower() == b.rstrip("/").lower()


async def consider(db: AsyncSession, task: Task, trigger: Trigger) -> str:
    """Send the task back for this trigger, escalate when the rounds are used up, or ignore it (and say why)."""
    from app.workflow import engine  # local: the workflow imports the git modules
    from app.workflow.models import Needs, RunRole, Stage, WorkflowStatus

    project = await db.get(Project, task.project_id)
    if project is None or not project.send_back_on_changes_requested:
        return "ignored:off"
    if trigger.host == "github" and trigger.association not in WRITE_ACCESS:
        return "ignored:no_write_access"
    wf = await engine.lock_task(db, task)
    if wf is None or wf.status != WorkflowStatus.waiting_human or wf.needs != Needs.human_code_review:
        return "ignored:not_waiting"
    if not _same(trigger.pr_url, wf.pr_url):
        return "ignored:other_pr"
    if not _same(wf.pr_fix_pr_url, wf.pr_url):  # a new pull request: its rounds start again
        wf.pr_fix_rounds, wf.pr_fix_pr_url = 0, wf.pr_url
    wf.pr_fix_trigger = {**asdict(trigger), "round": min(wf.pr_fix_rounds + 1, MAX_PR_FIX_ROUNDS)}
    if wf.pr_fix_rounds >= MAX_PR_FIX_ROUNDS:
        await engine.escalate(db, wf, "pr_fix_rounds_exhausted")
        return "exhausted"
    wf.pr_fix_rounds += 1
    await engine.record_workflow_event(db, task, None, "pr.sent_back", {
        "pr_url": wf.pr_url, "pr_number": trigger.pr_number, "by": trigger.by, "kind": trigger.kind,
        "excerpt": trigger.excerpt, "where": trigger.where, "round": wf.pr_fix_rounds, "of": MAX_PR_FIX_ROUNDS,
    })
    await engine.set_stage(db, wf, task, Stage.build)
    owner = await db.scalar(select(Agent.owner_id).where(Agent.id == task.assignee_agent_id))
    await engine.enqueue(db, wf, task, RunRole.pr_fix, requested_by=owner)
    return "sent_back"


def prompt_section(wf) -> str:
    """The fix run's own section: the pull request, its branch, the round, and what was asked (from the host: untrusted)."""
    from app.workflow.context import (
        wrap_untrusted,  # local: the workflow imports the git modules
    )

    t = wf.pr_fix_trigger or {}
    asked = f'{t.get("by") or "A reviewer"} asked: "{t.get("excerpt") or ""}"' + (f" at {t['where']}" if t.get("where") else "")
    return (
        "## Changes requested on the pull request\n"
        f"Pull request: {wf.pr_url} (branch {wf.branch}) · round {wf.pr_fix_rounds} of {MAX_PR_FIX_ROUNDS}\n"
        + wrap_untrusted("pull request review", asked)
    )


async def report_fix(db: AsyncSession, run, summary: str, tests_passed: bool) -> None:
    """A fix run reports its round: what it changed and whether the full test suite passed. A later report from the
    same run replaces it. The caller commits."""
    from fastapi import HTTPException, status

    from app.core.text import strip_nul
    from app.workflow import build  # local: the workflow imports the git modules
    from app.workflow.models import RunRole

    await build.lock_run_role(db, run, (RunRole.pr_fix,))
    if not isinstance(tests_passed, bool) or not isinstance(summary, str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_fix_report")
    run.step_result = {"summary": strip_nul(summary)[:MAX_SUMMARY], "tests_passed": tests_passed}
    await db.flush()


async def _handle_pr_fix(db: AsyncSession, wf, task: Task, run) -> None:
    """The fix run ended: pushed with passing tests, the workflow waits for the merge again; otherwise one nudge,
    then the human decides."""
    from app.git import service as git  # local: service imports the workflow
    from app.workflow import engine, finish
    from app.workflow.models import Needs, Stage

    if await finish._asked_or_answered(db, wf, task, run):
        return
    result = run.step_result or {}
    if result.get("tests_passed") is True:
        await engine.set_stage(db, wf, task, Stage.done)
        await engine.record_workflow_event(db, task, None, "pr.fix_pushed", {
            "pr_url": wf.pr_url, "pr_number": (wf.pr_fix_trigger or {}).get("pr_number"), "round": wf.pr_fix_rounds,
            "of": MAX_PR_FIX_ROUNDS, "summary": result.get("summary") or "",
        })
        await engine.wait_for(db, wf, Needs.human_code_review)
        await git.settle_done(db, wf, task, await git.pull_requests_of_task(db, task.id))
        return
    if not wf.nudged:
        wf.nudged = True
        await engine.rerun(db, wf, task, last=run, requested_by=await engine.owner_id(db, run), resume_kind="nudge",
                           payload=PR_FIX_NUDGE)
    else:
        await engine.escalate(db, wf, "pr_fix_incomplete")


async def _accept_back_to_waiting(db: AsyncSession, wf, task: Task, user) -> None:
    """The human accepts the pull request as it is: the workflow waits for its merge again, without a fix."""
    from app.workflow import engine
    from app.workflow.models import Needs, Stage

    await engine.set_stage(db, wf, task, Stage.done)
    await engine.wait_for(db, wf, Needs.human_code_review, actor_id=user.id)


async def cancel(db: AsyncSession, user, task: Task) -> None:
    """Don't send back: the fix run stops and the workflow waits for the merge again (the round still counts). The
    workflow leaves "running" before the run is cancelled, so the run's end is not taken for a failure."""
    from fastapi import HTTPException, status

    from app.agent_runs import service as runs  # local: agent runs import the workflow
    from app.workflow import engine
    from app.workflow.models import Needs, RunRole, Stage

    wf = await engine.lock_task(db, task)
    await engine.require_actor(db, user, task, wf)
    run = await engine.active_run(db, task.id)
    if wf is None or run is None or run.workflow_role != RunRole.pr_fix:
        raise HTTPException(status.HTTP_409_CONFLICT, "no_fix_running")
    await engine.set_stage(db, wf, task, Stage.done)
    await engine.wait_for(db, wf, Needs.human_code_review, actor_id=user.id)
    await engine.record_workflow_event(db, task, user.id, "pr.send_back_cancelled", {"pr_url": wf.pr_url})
    await runs.cancel_run(db, user, run)


def _register() -> None:
    from app.workflow import engine
    from app.workflow.models import RunRole

    engine.ROLE_HANDLERS[RunRole.pr_fix] = _handle_pr_fix
    engine.ACCEPT_HANDLERS["pr_fix_rounds_exhausted"] = _accept_back_to_waiting
    engine.ACCEPT_HANDLERS["pr_fix_incomplete"] = _accept_back_to_waiting


_register()
