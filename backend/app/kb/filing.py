"""Files approved designs and plans, and final reviews, in the project's Knowledge Base (WF-9, KB-4).

One Knowledge Base document per task and kind (KbFiling), in "Designs & Plans/<TASK-KEY>"; each newly
approved version adds a revision. Filing runs inside the approval's transaction, in a savepoint: a failure is
logged and audited and never undoes the approval.
"""

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.audit import service as audit
from app.auth.models import User
from app.kb import access, service
from app.kb.models import FilingKind, KbDocument, KbFiling
from app.projects.models import Project
from app.tasks.models import Task
from app.workflow.models import Mockup, StepReview, TaskWorkflow, WorkflowDocument

log = logging.getLogger(__name__)

FOLDER = "Designs & Plans"
TITLES = {FilingKind.design: "Design", FilingKind.plan: "Plan", FilingKind.review: "Final review"}


async def _author(db: AsyncSession, task: Task, fallback: User) -> tuple[User, uuid.UUID | None]:
    """The agent's owner with the agent; for a workflow without one (connect_only), the human assignee."""
    wf = (await db.execute(select(TaskWorkflow).where(TaskWorkflow.task_id == task.id))).scalar_one_or_none()
    agent_id = task.assignee_agent_id or (wf.agent_id if wf else None)
    agent = await db.get(Agent, agent_id) if agent_id else None
    if agent is not None:
        return await db.get(User, agent.owner_id), agent.id
    if task.assignee_user_id:
        return await db.get(User, task.assignee_user_id), None
    return fallback, None


async def _file(
    db: AsyncSession, task: Task, kind: FilingKind, body: str, summary: str, fallback_author: User
) -> KbDocument:
    project = await db.get(Project, task.project_id)
    key = f"{project.key}-{task.number}"
    full = f"# {key} — {task.title}\n\n{body}"
    author, agent_id = await _author(db, task, fallback_author)
    filed = (
        await db.execute(
            select(KbFiling).where(KbFiling.task_id == task.id, KbFiling.kind == kind).with_for_update()
        )
    ).scalar_one_or_none()
    if filed is not None:
        doc = await service.lock_document(db, filed.document_id)
        if doc.body_md == full:
            return doc  # this version is already filed
        return await service.update_document(
            db, author, doc, base_revision=doc.latest_revision, body=full, summary=summary[:200], agent_id=agent_id
        )
    space = await access.space_for_project(db, project.id)
    top = await service.ensure_folder(db, None, space, None, FOLDER)
    sub = await service.ensure_folder(db, None, space, top.id, key)
    title = await service.free_title(db, space.id, sub.id, TITLES[kind])
    doc = await service.create_document(
        db, author, space, sub.id, title, full, agent_id=agent_id, summary=summary[:200]
    )
    db.add(KbFiling(task_id=task.id, kind=kind, document_id=doc.id))
    await db.flush()
    return doc


async def _safely(db: AsyncSession, task: Task, kind: FilingKind, actor_id: uuid.UUID | None, *args) -> None:
    try:
        async with db.begin_nested():
            await _file(db, task, kind, *args)
    except Exception:
        log.exception("filing %s of task %s in the Knowledge Base failed", kind, task.id)
        await audit.record(db, "kb.filing_failed", actor_id=actor_id, target_type="task", target_id=task.id,
                           data={"kind": str(kind)})


async def file_document(db: AsyncSession, task: Task, kind, doc: WorkflowDocument, approver: User) -> None:
    kind = FilingKind(str(kind))
    body = doc.body_md
    mockup = await db.get(Mockup, doc.mockup_id) if doc.mockup_id else None
    if mockup is not None:  # WF-6d: the approved mockup stays in MegooColab; the filed design links to it
        body += f"\n\n---\nApproved mockup: v{mockup.version} — {mockup.title} (/api/mockups/{mockup.id}/view)"
    await _safely(db, task, kind, approver.id, body, f"Approved v{doc.version} by {approver.name}", approver)


def _longest_backticks(text: str) -> int:
    return max((len(m) for m in re.findall(r"`+", text)), default=0)


def _fenced(text: str) -> str:
    """A fenced block the text cannot close: agent-written text stays inert Markdown."""
    fence = "`" * max(4, _longest_backticks(text) + 1)
    return f"{fence}text\n{text}\n{fence}"


def _code_span(text: str) -> str:
    text = " ".join(text.split())
    ticks = "`" * (_longest_backticks(text) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{ticks}{pad}{text}{pad}{ticks}"


def review_body(review: StepReview) -> str:
    lines = [f"Final review — Round {review.round}: **{review.verdict}**", ""]
    findings = list(review.findings or [])
    if not findings:
        lines.append("No findings.")
    else:
        lines += ["## Findings", ""]
        for f in findings:
            where = f.get("file") or "(no file)"
            if f.get("line"):
                where = f"{where}:{f['line']}"
            # severity is one of three fixed words; the file and summary come from the agent
            lines.append(f"- **{f.get('severity', 'minor')}** {_code_span(where)}")
            lines.append("")
            lines.append(_fenced(str(f.get("summary", ""))))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def file_final_review(db: AsyncSession, task: Task, review: StepReview, *, summary: str, actor: User) -> None:
    await _safely(db, task, FilingKind.review, actor.id, review_body(review), summary, actor)


async def kb_documents(db: AsyncSession, task_id: uuid.UUID) -> list[dict]:
    rows = await db.execute(select(KbFiling).where(KbFiling.task_id == task_id).order_by(KbFiling.kind))
    return [{"kind": f.kind, "document_id": f.document_id} for f in rows.scalars()]
