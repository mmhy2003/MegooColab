"""Memory in stage prompts (MEM-6): the summary cards of the task's project, its teams and the organization,
then the conclusions most relevant to the task, all within the agent owner's readable scopes."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kb.context import _owner
from app.memory.access import readable_scopes
from app.memory.models import EntityKind, MemCard, MemEntity, ScopeKind
from app.memory.search import search_conclusions
from app.projects.models import ProjectTeam
from app.tasks.models import Task
from app.workflow import context
from app.workflow.context import _escape, wrap_untrusted
from app.workflow.models import RunRole

HEADING = "## Memory\n"
NOTE = "What the organization's memory knows that may matter here (ask more with ask_memory):\n"
BUDGET = 6000
CONCLUSIONS = 10
DESCRIPTION_CHARS = 1000
SKIP_ROLES = frozenset({RunRole.finish})


async def _cards(db: AsyncSession, task: Task, scopes) -> list[tuple[str, str]]:
    """(entity name, summary) for the project, then its teams, then the org, each in its own scope."""
    teams = list((await db.execute(select(ProjectTeam.team_id).where(ProjectTeam.project_id == task.project_id))).scalars())
    wanted = [
        (MemEntity.project_id == task.project_id, MemCard.scope_kind == ScopeKind.project),
        (MemEntity.team_id.in_(teams), MemCard.scope_kind == ScopeKind.team),
        (MemEntity.kind == EntityKind.org, MemCard.scope_kind == ScopeKind.org),
    ]
    out: list[tuple[str, str]] = []
    for entity_clause, scope_clause in wanted:
        rows = await db.execute(
            select(MemEntity.name, MemCard.summary_md)
            .join(MemEntity, MemEntity.id == MemCard.entity_id)
            .where(entity_clause, scope_clause, scopes.clause(MemCard))
            .order_by(MemEntity.name)
        )
        out += [(name, summary) for name, summary in rows if summary.strip()]
    return out


async def memory_context(db: AsyncSession, task: Task, role: RunRole) -> str | None:
    if role in SKIP_ROLES:
        return None
    owner = await _owner(db, task)
    if owner is None:
        return None
    scopes = await readable_scopes(db, owner)
    cards = await _cards(db, task, scopes)
    query = f"{task.title}\n{(task.description_md or '')[:DESCRIPTION_CHARS]}"
    conclusions = await search_conclusions(db, owner, query, project_id=task.project_id, limit=CONCLUSIONS)
    if not cards and not conclusions:
        return None
    section = HEADING + NOTE
    overhead = len(wrap_untrusted("memory", ""))
    for name, summary in cards:
        header = f"\n### {_escape(' '.join(name.split()))}\n"
        room = BUDGET - len(section) - len(header) - overhead - 1
        if room < 100:
            break
        text = _escape(summary.strip())
        if len(text) > room:
            text = text[: room - 1].rstrip() + "…"
        section += header + wrap_untrusted("memory", text) + "\n"
    if conclusions:
        header = "\n### Relevant conclusions\n"
        room = BUDGET - len(section) - len(header) - overhead - 1
        lines: list[str] = []
        for c in conclusions:
            line = f"- {_escape(' '.join(c.text.split()))} ({c.kind})"
            if sum(len(x) + 1 for x in lines) + len(line) > room:
                break
            lines.append(line)
        if lines:
            section += header + wrap_untrusted("memory", "\n".join(lines)) + "\n"
    return section.rstrip() + "\n" if "### " in section else None


def register() -> None:
    if memory_context not in context.context_providers:
        context.context_providers.append(memory_context)
