"""An agent reviews the task's pull request (piece 4). With the project's "Pull request review" set to Agent, a review
run of the reviewer (the project's chosen agent, else the task's own agent in a fresh session) posts its review on
the host from the owner's account, merges when it approves, and reports; what follows is decided here."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.models import Task, TaskEvent
from app.workflow.models import Needs

MAX_FINDINGS = 50
MAX_SUMMARY = 4000
SEVERITIES = ("critical", "important", "minor")


async def review_round(db: AsyncSession, wf) -> int:
    """This pull request's review round: the reviews already reported on it, plus one."""
    done = await db.scalar(
        select(func.count()).select_from(TaskEvent).where(
            TaskEvent.task_id == wf.task_id, TaskEvent.kind == "pr.agent_reviewed",
            TaskEvent.data["pr_url"].astext == (wf.pr_url or ""),
        )
    )
    return int(done or 0) + 1


async def prompt_section(db: AsyncSession, wf) -> str:
    """The review run's own section: the pull request, its branch and the round (stated by MegooColab, not untrusted)."""
    return (
        "## Pull request to review\n"
        f"Pull request: {wf.pr_url} (branch {wf.branch}) · review round {await review_round(db, wf)}"
    )


REVIEW_NUDGE = "Review the pull request, post your review on the host, then call submit_pr_review with your verdict."


async def review_if_agent(db: AsyncSession, wf, task: Task) -> None:
    """The workflow just started waiting for the merge of its pull request: with an agent's review, the reviewer
    reviews it now."""
    from app.projects.models import Project, PrReview
    from app.workflow import engine

    if engine.pr_review_mode(await db.get(Project, task.project_id), wf) == PrReview.agent:
        await start_review(db, wf, task)


async def start_review(db: AsyncSession, wf, task: Task, **enqueue_args) -> None:
    """A review run of the reviewer: the project's chosen agent (bound to the project), else the task's own agent.
    The caller holds the workflow lock."""
    from app.agents.models import Agent, AgentBinding
    from app.projects.models import Project
    from app.workflow import engine
    from app.workflow.models import RunRole

    project = await db.get(Project, task.project_id)
    reviewer = project.pr_reviewer_agent_id or task.assignee_agent_id
    bound = reviewer == task.assignee_agent_id or await db.scalar(
        select(AgentBinding.id).where(AgentBinding.agent_id == reviewer, AgentBinding.project_id == project.id)
    )
    if reviewer is None or task.assignee_agent_id is None or not bound:
        await engine.escalate(db, wf, "agent_review_unavailable")
        return
    owner = await db.scalar(select(Agent.owner_id).where(Agent.id == reviewer))
    other = reviewer if reviewer != task.assignee_agent_id else None
    await engine.enqueue(db, wf, task, RunRole.pr_review, requested_by=owner, agent_id=other, **enqueue_args)


async def _handle_pr_review(db: AsyncSession, wf, task: Task, run) -> None:
    """The review run ended. Its review is recorded; the workflow waits for the merge (a merge or close seen
    meanwhile settles first); then: merged, wait for MegooColab to see it; approved but not merged, a person
    decides; changes requested, the task goes back to its agent; no verdict, one nudge, then a person decides."""
    from app.agents.models import Agent
    from app.git import send_back
    from app.git import service as git
    from app.workflow import engine, finish
    from app.workflow.models import Stage

    if await finish._asked_or_answered(db, wf, task, run):
        return
    result = run.step_result or {}
    agent = await db.get(Agent, run.agent_id)
    number = _pr_number(wf.pr_url)
    if result.get("verdict"):
        await engine.record_workflow_event(db, task, None, "pr.agent_reviewed", {
            "pr_url": wf.pr_url, "pr_number": number, "verdict": result["verdict"], "summary": result.get("summary"),
            "findings": len(result.get("findings") or []), "merged": bool(result.get("merged")),
            "merge_error": result.get("merge_error"), "agent_id": str(run.agent_id),
            "agent_name": agent.name if agent else None,
        })
    await engine.set_stage(db, wf, task, Stage.done)
    # a resting state: what comes next is decided below (an escalation tells people itself)
    await rest_after_merge(db, wf, task)
    await git.queue_refresh(db, task.id)  # a merge it made is seen soon, not at the next poll
    if await git.settle_done(db, wf, task, await git.pull_requests_of_task(db, task.id)):
        return
    verdict = result.get("verdict")
    if verdict is None:
        if not wf.nudged:
            wf.nudged = True
            await engine.rerun(db, wf, task, last=run, requested_by=await engine.owner_id(db, run),
                               resume_kind="nudge", payload=REVIEW_NUDGE)
        else:
            await engine.escalate(db, wf, "agent_review_incomplete")
        return
    wf.nudged = False
    if verdict == "approved":
        if result.get("merged"):
            return
        if result.get("merge_blocked_by") == "conflict" and task.assignee_agent_id is not None:
            # the base branch moved on under the pull request: the task's own agent brings it in and resolves it
            trigger = send_back.Trigger(
                kind="merge_conflict", pr_url=wf.pr_url, pr_number=number, by=agent.name if agent else "The reviewer",
                excerpt=(result.get("merge_error") or "The pull request has conflicts with its base branch.")[:280],
                where=None, association=None, host="agent",
            )
            await send_back.send_back_now(db, wf, task, trigger)
            return
        await engine.escalate(db, wf, "agent_merge_failed")
        return
    first = (result.get("findings") or [None])[0] or {}
    where = f"{first['file']}:{first['line']}" if first.get("file") and first.get("line") else (first.get("file") or None)
    trigger = send_back.Trigger(
        kind="agent_review", pr_url=wf.pr_url, pr_number=number, by=agent.name if agent else "The reviewer",
        excerpt=(result.get("summary") or "")[:280], where=where, association=None, host="agent",
    )
    await send_back.send_back_now(db, wf, task, trigger)


async def merge_wait(db: AsyncSession, wf, task: Task) -> Needs:
    """What the round waits on once its agent review ended: `merge_confirmation` (nobody is asked) when MegooColab
    can see the merge by itself; else `human_code_review`, as a person has to act: a back-merge pull request is
    theirs to merge, and an untracked or other-branch main one is never settled from the host."""
    from app.git.models import PR_MAIN, TaskPullRequest

    if wf.back_merge_pr_url:
        return Needs.human_code_review
    row = await db.get(TaskPullRequest, (task.id, PR_MAIN))
    if row is None or row.connection_id is None or row.error == "branch_mismatch":
        return Needs.human_code_review
    return Needs.merge_confirmation


async def rest_after_merge(db: AsyncSession, wf, task: Task) -> None:
    """The round rests after its agent review, telling nobody. Waiting on `merge_confirmation`, the main row's read
    failures count from now and it is read again at once. The caller holds the workflow lock (lock order: task,
    workflow, then the row)."""
    from app.git import service as git
    from app.git.models import PR_MAIN
    from app.workflow import engine

    need = await merge_wait(db, wf, task)
    await engine.wait_for(db, wf, need, notify=False)
    if need != Needs.merge_confirmation:
        return
    row = await git._lock_row(db, task.id, PR_MAIN)
    if row is not None:
        row.failures = 0
        row.next_check_at = git._now()
        await db.flush()


def _pr_number(url: str | None) -> int | None:
    import re

    m = re.search(r"/(?:pull|pulls|merge_requests)/(\d+)/?$", url or "")
    return int(m.group(1)) if m else None


async def _accept_waits_for_the_merge(db: AsyncSession, wf, task: Task, user) -> None:
    """A person takes over: the workflow waits for the pull request's merge (a merge seen meanwhile settles)."""
    from app.git import service as git
    from app.workflow import engine
    from app.workflow.models import Needs, Stage

    await engine.set_stage(db, wf, task, Stage.done)
    await engine.wait_for(db, wf, Needs.human_code_review, actor_id=user.id)
    await git.settle_done(db, wf, task, await git.pull_requests_of_task(db, task.id))


async def _retry_review(db: AsyncSession, wf, task: Task, user) -> None:
    """Retry after the reviewer was unavailable (now bound, say): the review starts again."""
    await start_review(db, wf, task)


async def _accept_unconfirmed(db: AsyncSession, wf, task: Task, user) -> None:
    """The agent's merge couldn't be confirmed, and a person says it merged (Mark merged): the round finishes."""
    from app.workflow import finish

    await finish.mark_merged(db, wf, task, user)


async def _retry_confirmation(db: AsyncSession, wf, task: Task, user) -> None:
    """Retry confirming the agent's merge: the round rests again as after its review (`merge_wait`), and the pull
    request is read again. That is back on `merge_confirmation` (its failures counted afresh) when MegooColab can
    still see the merge by itself; else, with the main pull request now untracked or of another branch (a cause
    `untracked` or `branch_mismatch`), on `human_code_review`, as a person has to confirm it. No agent runs."""
    from app.git import service as git

    wf.escalation_reason = None  # as the decision does: the wait is no longer an escalation
    await rest_after_merge(db, wf, task)
    await git.queue_refresh(db, task.id)
    # a merge (or close) already stored, say seen while paused, changes nothing on a later read: settle it now
    await git.settle_done(db, wf, task, await git.pull_requests_of_task(db, task.id))


def _register() -> None:
    from app.workflow import engine
    from app.workflow.models import RunRole

    engine.ROLE_HANDLERS[RunRole.pr_review] = _handle_pr_review
    for reason in ("agent_merge_failed", "agent_review_incomplete", "agent_review_unavailable"):
        engine.ACCEPT_HANDLERS[reason] = _accept_waits_for_the_merge
    engine.RETRY_HANDLERS["agent_review_unavailable"] = _retry_review
    engine.ACCEPT_HANDLERS["merge_not_confirmed"] = _accept_unconfirmed
    engine.RETRY_HANDLERS["merge_not_confirmed"] = _retry_confirmation


_register()


def _finding(item: object) -> dict:
    from app.core.text import strip_nul

    if not isinstance(item, dict) or item.get("severity") not in SEVERITIES or not isinstance(item.get("summary"), str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_finding")
    line = item.get("line")
    return {"severity": item["severity"], "file": strip_nul(str(item.get("file") or ""))[:500],
            "line": line if isinstance(line, int) and not isinstance(line, bool) else None,
            "summary": strip_nul(item["summary"])[:2000]}


MERGE_BLOCKERS = ("conflict", "checks", "protection", "other")


async def report(db: AsyncSession, run, verdict: str, summary: str, findings: list, merged: bool,
                 merge_error: str | None, *, merge_blocked_by: str | None = None) -> None:
    """A review run reports its review. A later report from the same run replaces it. The caller commits."""
    from app.core.text import strip_nul
    from app.workflow import build  # local: the workflow imports the git modules
    from app.workflow.models import RunRole

    await build.lock_run_role(db, run, (RunRole.pr_review,))
    if verdict not in ("approved", "changes_requested") or not isinstance(summary, str) or not isinstance(merged, bool):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_review")
    if merge_blocked_by is not None and merge_blocked_by not in MERGE_BLOCKERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_review")
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_many_findings")
    run.step_result = {
        "verdict": verdict, "summary": strip_nul(summary)[:MAX_SUMMARY], "findings": [_finding(f) for f in findings],
        "merged": merged and verdict == "approved",
        "merge_error": strip_nul(merge_error)[:500] if isinstance(merge_error, str) and merge_error else None,
        # what refused the merge: a conflict sends the task back to its agent; anything else is a person's to decide
        "merge_blocked_by": merge_blocked_by if verdict == "approved" and not merged else None,
    }
    await db.flush()
