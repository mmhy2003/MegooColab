"""An agent reviews the task's pull request (piece 4). With the project's "Pull request review" set to Agent, a review
run of the reviewer (the project's chosen agent, else the task's own agent in a fresh session) posts its review on
the host from the owner's account, merges when it approves, and reports; what follows is decided here."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.models import TaskEvent

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


def _finding(item: object) -> dict:
    from app.core.text import strip_nul

    if not isinstance(item, dict) or item.get("severity") not in SEVERITIES or not isinstance(item.get("summary"), str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_finding")
    line = item.get("line")
    return {"severity": item["severity"], "file": strip_nul(str(item.get("file") or ""))[:500],
            "line": line if isinstance(line, int) and not isinstance(line, bool) else None,
            "summary": strip_nul(item["summary"])[:2000]}


async def report(db: AsyncSession, run, verdict: str, summary: str, findings: list, merged: bool,
                 merge_error: str | None) -> None:
    """A review run reports its review. A later report from the same run replaces it. The caller commits."""
    from app.core.text import strip_nul
    from app.workflow import build  # local: the workflow imports the git modules
    from app.workflow.models import RunRole

    await build.lock_run_role(db, run, (RunRole.pr_review,))
    if verdict not in ("approved", "changes_requested") or not isinstance(summary, str) or not isinstance(merged, bool):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_review")
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_many_findings")
    run.step_result = {
        "verdict": verdict, "summary": strip_nul(summary)[:MAX_SUMMARY], "findings": [_finding(f) for f in findings],
        "merged": merged and verdict == "approved",
        "merge_error": strip_nul(merge_error)[:500] if isinstance(merge_error, str) and merge_error else None,
    }
    await db.flush()
