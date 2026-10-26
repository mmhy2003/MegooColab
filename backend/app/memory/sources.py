"""What the memory learns from (MEM-2) and how a source is turned into text for extraction.

Every source change queues `mem.extract` a minute later (deduplicated), so a burst of edits is read once.
Runs contribute metadata only: the agent's summary and messages, never file contents (NFR-2).
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun
from app.agents.models import Agent
from app.jobs import queue
from app.kb.models import KbDocument, KbSpace, SpaceKind
from app.memory.access import Scope
from app.memory.entities import ensure_entity, org_entity
from app.memory.models import EntityKind, MemEntity, MemProductProject, ScopeKind
from app.projects.models import Project, ProjectTeam
from app.tasks.models import Comment, Task, TaskEvent
from app.workflow.models import StepReview

SourceKind = Literal["task", "comment", "run", "review", "kb_document", "answer"]
TEXT_LIMIT = 12_000
LABEL_LIMIT = 200
EXTRACT_DELAY = timedelta(seconds=60)


@dataclass
class Source:
    kind: str
    id: uuid.UUID
    scope: Scope
    text: str
    label: str
    link: str
    candidates: list[MemEntity] = field(default_factory=list)


async def queue_extract(db: AsyncSession, kind: str, source_id: uuid.UUID) -> None:
    await queue.enqueue(
        db,
        "mem.extract",
        {"source_kind": kind, "source_id": str(source_id)},
        dedupe_key=f"mem.extract:{kind}:{source_id}",
        run_after=func.now() + EXTRACT_DELAY,
    )


# -- candidates --------------------------------------------------------------------------------------


class _Candidates:
    def __init__(self) -> None:
        self.items: list[MemEntity] = []

    def add(self, entity: MemEntity | None) -> None:
        if entity is not None and all(e.id != entity.id for e in self.items):
            self.items.append(entity)


async def _scope_candidates(db: AsyncSession, scope: Scope) -> _Candidates:
    """The scope's own entity first, then the org, then (for a project) its teams."""
    out = _Candidates()
    kind, ref = scope
    if kind == ScopeKind.project:
        out.add(await ensure_entity(db, EntityKind.project, ref))
    elif kind == ScopeKind.team:
        out.add(await ensure_entity(db, EntityKind.team, ref))
    out.add(await org_entity(db))
    if kind == ScopeKind.project:
        for team_id in (await db.execute(select(ProjectTeam.team_id).where(ProjectTeam.project_id == ref))).scalars():
            out.add(await ensure_entity(db, EntityKind.team, team_id))
    return out


async def _add_products(db: AsyncSession, out: _Candidates, project_id: uuid.UUID | None, text: str) -> None:
    products = (await db.execute(select(MemEntity).where(MemEntity.kind == EntityKind.product))).scalars().all()
    linked: set[uuid.UUID] = set()
    if project_id is not None:
        linked = set(
            (
                await db.execute(
                    select(MemProductProject.product_entity_id).where(MemProductProject.project_id == project_id)
                )
            ).scalars()
        )
    for p in products:
        if p.id in linked or re.search(rf"(?<!\w){re.escape(p.name)}(?!\w)", text, re.IGNORECASE):
            out.add(p)


async def _add_task_people(db: AsyncSession, out: _Candidates, task: Task) -> None:
    if task.assignee_user_id:
        out.add(await ensure_entity(db, EntityKind.user, task.assignee_user_id))
    if task.assignee_agent_id:
        out.add(await ensure_entity(db, EntityKind.agent, task.assignee_agent_id))


async def _add_agent(db: AsyncSession, out: _Candidates, agent_id: uuid.UUID | None) -> None:
    agent = await db.get(Agent, agent_id) if agent_id else None
    if agent is not None:
        out.add(await ensure_entity(db, EntityKind.agent, agent.id))
        out.add(await ensure_entity(db, EntityKind.user, agent.owner_id))


# -- loaders -----------------------------------------------------------------------------------------


def _clip(text: str) -> str:
    return text.strip()[:TEXT_LIMIT]


async def _task_context(db: AsyncSession, task: Task) -> tuple[Project, Scope, str, str]:
    project = await db.get(Project, task.project_id)
    key = f"{project.key}-{task.number}"
    return project, (ScopeKind.project, project.id), key, f"/projects/{project.key}/tasks/{task.number}"


async def _task_source(db: AsyncSession, kind: str, sid: uuid.UUID, task: Task, text: str, label: str) -> Source:
    _project, scope, _, link = await _task_context(db, task)
    out = await _scope_candidates(db, scope)
    await _add_task_people(db, out, task)
    return Source(kind, sid, scope, text, label[:LABEL_LIMIT], link, out.items)


async def _load_task(db: AsyncSession, sid: uuid.UUID) -> Source | None:
    task = await db.get(Task, sid)
    if task is None:
        return None
    _, _, key, _ = await _task_context(db, task)
    src = await _task_source(db, "task", sid, task, _clip(f"{task.title}\n\n{task.description_md or ''}"),
                             f"{key}: {task.title}")
    await _add_products(db, _wrap(src), task.project_id, src.text)
    return src


async def _load_comment(db: AsyncSession, sid: uuid.UUID) -> Source | None:
    comment = await db.get(Comment, sid)
    task = await db.get(Task, comment.task_id) if comment else None
    if task is None:
        return None
    _, _, key, _ = await _task_context(db, task)
    src = await _task_source(db, "comment", sid, task, _clip(comment.body_md), f"Comment on {key}")
    out = _wrap(src)
    if comment.author_user_id:
        out.add(await ensure_entity(db, EntityKind.user, comment.author_user_id))
    await _add_products(db, out, task.project_id, src.text)
    return src


async def _load_run(db: AsyncSession, sid: uuid.UUID) -> Source | None:
    run = await db.get(AgentRun, sid)
    task = await db.get(Task, run.task_id) if run else None
    if task is None:
        return None
    parts = [run.summary.strip()] if run.summary and run.summary.strip() else []
    messages = await db.execute(
        select(TaskEvent.data)
        .where(TaskEvent.task_id == task.id, TaskEvent.kind == "agent_message",
               TaskEvent.data["run_id"].astext == str(run.id))
        .order_by(TaskEvent.created_at.desc())
    )
    size = sum(len(p) for p in parts)
    for data in messages.scalars():
        line = str(data.get("text") or "").strip()
        if not line:
            continue
        if size + len(line) + 1 > TEXT_LIMIT:
            break
        parts.append(line)
        size += len(line) + 1
    _, _, key, _ = await _task_context(db, task)
    src = await _task_source(db, "run", sid, task, _clip("\n".join(parts)), f"Agent run on {key}")
    out = _wrap(src)
    await _add_agent(db, out, run.agent_id)
    await _add_products(db, out, task.project_id, src.text)
    return src


async def _load_review(db: AsyncSession, sid: uuid.UUID) -> Source | None:
    review = await db.get(StepReview, sid)
    task = await db.get(Task, review.task_id) if review else None
    if task is None:
        return None
    lines = [f"Review verdict: {review.verdict}"]
    for f in review.findings or []:
        where = f"{f.get('file') or ''}{':' + str(f['line']) if f.get('line') else ''}"
        lines.append(f"{f.get('severity', 'minor')} {where} {f.get('summary', '')}".strip())
    _, _, key, _ = await _task_context(db, task)
    src = await _task_source(db, "review", sid, task, _clip("\n".join(lines)), f"Review of {key}")
    out = _wrap(src)
    run = await db.get(AgentRun, review.run_id)
    await _add_agent(db, out, run.agent_id if run else None)
    await _add_products(db, out, task.project_id, src.text)
    return src


async def _load_kb_document(db: AsyncSession, sid: uuid.UUID) -> Source | None:
    doc = await db.get(KbDocument, sid)
    space = await db.get(KbSpace, doc.space_id) if doc else None
    if space is None:
        return None
    scope: Scope = {
        SpaceKind.org: (ScopeKind.org, None),
        SpaceKind.team: (ScopeKind.team, space.team_id),
        SpaceKind.project: (ScopeKind.project, space.project_id),
    }[SpaceKind(space.kind)]
    text = _clip(f"{doc.title}\n\n{doc.body_md}")
    out = await _scope_candidates(db, scope)
    await _add_products(db, out, space.project_id, text)
    return Source("kb_document", sid, scope, text, doc.title[:LABEL_LIMIT], f"/kb/doc/{doc.id}", out.items)


def _wrap(src: Source) -> _Candidates:
    """Adds to an existing source's candidate list in place."""
    out = _Candidates()
    out.items = src.candidates
    return out


SOURCE_LOADERS = {
    "task": _load_task,
    "comment": _load_comment,
    "run": _load_run,
    "review": _load_review,
    "kb_document": _load_kb_document,
}


async def load_source(db: AsyncSession, kind: str, source_id: uuid.UUID | str) -> Source | None:
    loader = SOURCE_LOADERS.get(kind)
    if loader is None:
        return None
    src = await loader(db, uuid.UUID(str(source_id)))
    if src is None or not src.text.strip():
        return None
    return src
