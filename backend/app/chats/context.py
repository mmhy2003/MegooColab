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


FREESTYLE_TASKS = """## Working on the board

You can work on this project's board ({key}) with the rights of this agent's owner: what they can't do there, you
can't either.

- Read: list_tasks(project_key="{key}") (type="epic" lists the epics), get_task(key), list_sprints(project_key="{key}").
- Tasks and epics (an epic is a task of type epic): create_task(project_key="{key}", title, type, description_md),
  update_task(key, title, description_md, type, priority, story_points, epic_key) (epic_key="" takes a task out of
  its epic), move_task(key, column), delete_task(key).
- Sprints: create_sprint(project_key="{key}", name, start_date, end_date, goal), update_sprint(sprint, ...),
  start_sprint(sprint), complete_sprint(sprint, move_open_to), delete_sprint(sprint), and set_task_sprint(key,
  sprint) to put a story, task or bug in a sprint (sprint=null takes it out). A sprint is named by its id or name.

How to go about it:

- When the person asks for a change, make it.
- When you think a change is worth making, ask first: say exactly what you'd change (the keys, and what each would
  become) and ask whether to go ahead. Make it only once they say yes.
- Delete a task, an epic or a sprint only when the person asked for that one, by its key or name, or said yes to
  your naming it. Deleting can't be undone.
- Never assign a task to anyone: assigning one can start an agent's work. A task you create lands in the first column
  with nobody assigned.
- When you create a task, write its description from the conversation: what was decided, what's still open, and the
  files or links that matter, so someone who wasn't here can pick it up. A link back to this chat is added for you.
- Each change you make shows in this chat. In your reply, say what you changed, with the keys."""


async def freestyle_tasks_context(db: AsyncSession, task: Task, role: RunRole) -> str | None:
    """A freestyle turn may work on its own project's board (tasks, epics and sprints): when, and how."""
    if role != RunRole.freestyle:
        return None
    from app.projects.models import Project  # local: projects import the workflow

    project = await db.get(Project, task.project_id)
    return FREESTYLE_TASKS.format(key=project.key)


def register() -> None:
    for provider in (earlier_rounds, freestyle_tasks_context):
        if provider not in context.context_providers:
            context.context_providers.append(provider)
