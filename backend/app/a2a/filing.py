"""An answered question becomes a Q&A document in the target project's Knowledge Base (A2A-6, KB-4), and a
memory source ("answer", MEM-2).

Filing runs inside the answer's transaction, in a savepoint: a failure is logged and audited and never undoes
the answer.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.models import Question, QuestionStatus
from app.agents.models import Agent
from app.audit import service as audit
from app.auth.models import User
from app.kb import access
from app.kb import service as kb
from app.kb.models import KbDocument
from app.kb.schemas import TITLE_MAX
from app.memory.models import ScopeKind
from app.memory.sources import (
    LABEL_LIMIT,
    Source,
    _add_agent,
    _add_products,
    _clip,
    _scope_candidates,
    _wrap,
)
from app.projects.models import Project

log = logging.getLogger(__name__)

FOLDER = "Q&A"


def body_of(q: Question) -> str:
    parts = ["## Question", "", q.body.strip(), ""]
    if q.context and q.context.strip():
        parts += ["## Context", "", q.context.strip(), ""]
    parts += ["## Answer", "", (q.answer_md or "").strip(), ""]
    if q.citations:
        parts += ["## Sources", ""]
        parts += [f"- `{c['path']}:{c['start_line']}-{c['end_line']}`" for c in q.citations]
    return "\n".join(parts).rstrip() + "\n"


async def _author(db: AsyncSession, q: Question) -> tuple[User, uuid.UUID | None]:
    """The answering agent's owner with the agent, or the human who answered."""
    agent = await db.get(Agent, q.answered_by_agent_id) if q.answered_by_agent_id else None
    if agent is not None:
        return await db.get(User, agent.owner_id), agent.id
    return await db.get(User, q.answered_by_user_id), None


async def _file(db: AsyncSession, q: Question) -> KbDocument:
    space = await access.space_for_project(db, q.target_project_id)
    folder = await kb.ensure_folder(db, None, space, None, FOLDER)
    title = await kb.free_title(db, space.id, folder.id, f"Q{q.number}: {q.title}"[:TITLE_MAX])
    author, agent_id = await _author(db, q)
    return await kb.create_document(
        db, author, space, folder.id, title, body_of(q), agent_id=agent_id, summary=f"Answer to Q{q.number}"
    )


async def file_answer(db: AsyncSession, q: Question) -> None:
    try:
        async with db.begin_nested():
            doc = await _file(db, q)
            q.kb_document_id = doc.id
            await db.flush()
    except Exception:
        log.exception("filing the answer to question %s in the Knowledge Base failed", q.id)
        await audit.record(db, "a2a.filing_failed", actor_id=q.answered_by_user_id, target_type="question",
                           target_id=q.id)


async def load_answer(db: AsyncSession, sid: uuid.UUID) -> Source | None:
    """Memory source "answer": the question and its answer, in the target project's scope."""
    q = await db.get(Question, sid)
    if q is None or q.status != QuestionStatus.answered or not q.answer_md:
        return None
    project = await db.get(Project, q.target_project_id)
    scope = (ScopeKind.project, project.id)
    text = _clip(f"{q.title}\n\n{q.body}\n\n{q.answer_md}")
    out = await _scope_candidates(db, scope)
    src = Source("answer", sid, scope, text, f"Q{q.number} to {project.key}: {q.title}"[:LABEL_LIMIT],
                 f"/questions/{q.id}", out.items)
    more = _wrap(src)
    await _add_agent(db, more, q.answered_by_agent_id)
    await _add_products(db, more, project.id, text)
    return src
