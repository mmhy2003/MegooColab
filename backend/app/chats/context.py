"""What a chat's later round knows of the earlier ones: their requests, approved plans and outcomes."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.models import Task
from app.workflow import context
from app.workflow.models import (
    DocKind,
    DocStatus,
    RunRole,
    TaskWorkflow,
    WorkflowDocument,
)

EARLIER_CHARS = 8_000
NEW_CHAT_HINT = (
    "If this request has nothing to do with the earlier rounds, say so in your first reply and suggest starting a "
    "new chat."
)
OUTCOMES = {"merged_local": "merged", "branch_kept": "branch {branch} kept"}


def outcome_line(wf: TaskWorkflow | None) -> str:
    """How a round ended, in words (also the "Add to the board" description)."""
    if wf is None or wf.finish_outcome is None:
        return "ended before finishing"
    if wf.finish_outcome == "pr_opened":
        return f"pull request {wf.pr_url}" if wf.pr_url else "pull request opened"
    return OUTCOMES.get(wf.finish_outcome, wf.finish_outcome).format(branch=wf.branch or "")


async def _block(db: AsyncSession, task: Task, wf: TaskWorkflow | None) -> str:
    plan = await db.scalar(
        select(WorkflowDocument)
        .where(WorkflowDocument.task_id == task.id, WorkflowDocument.kind == DocKind.plan,
               WorkflowDocument.status == DocStatus.approved)
        .order_by(WorkflowDocument.version.desc())
        .limit(1)
    )
    lines = [f"Round {task.chat_round}: " + context.wrap_untrusted("round_request", f"{task.title}\n\n{task.description_md}")]
    if plan is not None and plan.steps:
        # approved by a person, so not wrapped; escaped so it cannot open a fake wrapper
        lines.append("Approved plan: " + context._escape("; ".join(s.get("title", "") for s in plan.steps)))
    lines.append(f"Outcome: {outcome_line(wf)}")
    return "\n".join(lines)


async def earlier_rounds(db: AsyncSession, task: Task, role: RunRole) -> str | None:
    if task.chat_id is None or (task.chat_round or 1) <= 1:
        return None
    rows = (await db.execute(
        select(Task, TaskWorkflow)
        .outerjoin(TaskWorkflow, TaskWorkflow.task_id == Task.id)
        .where(Task.chat_id == task.chat_id, Task.chat_round < task.chat_round)
        .order_by(Task.chat_round)
    )).all()
    blocks = [await _block(db, t, wf) for t, wf in rows]
    head = "## Earlier rounds of this chat\nThis request continues a chat; what came before:"

    def render() -> str:
        return "\n\n".join([head, *blocks, NEW_CHAT_HINT])

    while len(render()) > EARLIER_CHARS and len(blocks) > 1:
        blocks.pop(0)  # the oldest round goes first
    return render()


def register() -> None:
    if earlier_rounds not in context.context_providers:
        context.context_providers.append(earlier_rounds)
