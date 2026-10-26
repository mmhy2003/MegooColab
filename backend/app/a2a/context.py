"""Answers from other projects in stage prompts (A2A-6): the answered questions asked from the task, those the
agent's owner can read, each wrapped as untrusted (NFR-3)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.access import can_read_question
from app.a2a.models import Question, QuestionStatus
from app.kb.context import _owner
from app.projects.models import Project
from app.tasks.models import Task
from app.workflow import context
from app.workflow.context import _escape, wrap_untrusted
from app.workflow.models import RunRole

HEADING = "## Answers from other projects\n"
NOTE = "Questions this task asked other projects, and their answers (read more with get_question):\n"
BUDGET = 6000
MIN_ANSWER = 100
SKIP_ROLES = frozenset({RunRole.finish})


def _answer_text(q: Question) -> str:
    lines = [(q.answer_md or "").strip()]
    if q.citations:
        lines += ["", "Sources:"] + [f"- {c['path']}:{c['start_line']}-{c['end_line']}" for c in q.citations]
    return "\n".join(lines)


async def a2a_context(db: AsyncSession, task: Task, role: RunRole) -> str | None:
    if role in SKIP_ROLES:
        return None
    owner = await _owner(db, task)
    if owner is None:
        return None
    rows = await db.execute(
        select(Question)
        .where(Question.from_task_id == task.id, Question.status == QuestionStatus.answered)
        .order_by(Question.answered_at, Question.id)
    )
    section = HEADING + NOTE
    overhead = len(wrap_untrusted("answer", ""))
    shown = 0
    for q in rows.scalars():
        if not await can_read_question(db, owner, q):
            continue
        project = await db.get(Project, q.target_project_id)
        header = f"\n### {project.key}-Q{q.number}: {_escape(' '.join(q.title.split()))}\n"
        room = BUDGET - len(section) - len(header) - overhead - 1
        if room < MIN_ANSWER:
            break
        text = _escape(_answer_text(q))
        if len(text) > room:
            text = text[: room - 1].rstrip() + "…"
        section += header + wrap_untrusted("answer", text) + "\n"
        shown += 1
    return section.rstrip() + "\n" if shown else None


def register() -> None:
    if a2a_context not in context.context_providers:
        context.context_providers.append(a2a_context)
