"""Knowledge Base excerpts for stage prompts (WF-4): what the agent's owner could find themselves.

The task's title and the start of its description are the query. Up to MAX_DOCS documents, each with its best
matching chunk, fit in BUDGET characters; every excerpt is wrapped as untrusted (NFR-3).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.auth.models import User, UserStatus
from app.kb import search
from app.kb.models import KbDocument
from app.tasks.models import Task
from app.workflow import context
from app.workflow.context import _escape as escape
from app.workflow.context import wrap_untrusted
from app.workflow.models import RunRole, TaskWorkflow

HEADING = "## Knowledge Base\n"
NOTE = "Possibly relevant Knowledge Base entries (read more with kb_read):\n"
MAX_DOCS = 5
BUDGET = 8000
DESCRIPTION_CHARS = 1000
MIN_EXCERPT = 200
SKIP_ROLES = frozenset({RunRole.finish})


async def _owner(db: AsyncSession, task: Task) -> User | None:
    wf = (await db.execute(select(TaskWorkflow).where(TaskWorkflow.task_id == task.id))).scalar_one_or_none()
    agent_id = task.assignee_agent_id or (wf.agent_id if wf else None)
    user_id = None
    if agent_id is not None:
        user_id = await db.scalar(select(Agent.owner_id).where(Agent.id == agent_id))
    elif task.assignee_user_id is not None:
        user_id = task.assignee_user_id
    user = await db.get(User, user_id) if user_id else None
    return user if user is not None and user.status == UserStatus.active else None


async def kb_context(db: AsyncSession, task: Task, role: RunRole) -> str | None:
    if role in SKIP_ROLES:
        return None
    owner = await _owner(db, task)
    if owner is None:
        return None
    query = f"{task.title}\n{(task.description_md or '')[:DESCRIPTION_CHARS]}"
    found = await search.search(db, owner, query, limit=MAX_DOCS, match_any=True)
    if not found["results"]:
        return None
    section = HEADING + NOTE
    overhead = len(wrap_untrusted("kb", ""))
    for hit in found["results"]:
        name = f"{hit['path']}/{hit['title']}" if hit["path"] else hit["title"]
        revision = await db.scalar(select(KbDocument.latest_revision).where(KbDocument.id == hit["document_id"]))
        # titles and folder names are written by people and agents too
        header = f"\n### {escape(' '.join(name.split()))} (rev {revision})\n"
        room = BUDGET - len(section) - len(header) - overhead - 1
        if room < MIN_EXCERPT:
            break
        # escaping is idempotent, so the escaped text can be cut to size before wrapping
        excerpt = escape(hit["excerpt"].strip())
        if len(excerpt) > room:
            excerpt = excerpt[: room - 1].rstrip() + "…"
        section += header + wrap_untrusted("kb", excerpt) + "\n"
    return section.rstrip() + "\n" if "### " in section else None


def register() -> None:
    if kb_context not in context.context_providers:
        context.context_providers.append(kb_context)
