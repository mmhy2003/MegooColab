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
