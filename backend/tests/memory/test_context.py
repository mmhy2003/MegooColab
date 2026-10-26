"""Memory in stage prompts (MEM-6): cards and relevant conclusions, the agent owner's scopes only."""

import uuid

from app.agents.models import Agent, AgentProgram
from app.memory import context as mem_context
from app.memory import entities
from app.memory.models import EntityKind, MemCard, ScopeKind
from app.tasks.models import Task
from app.workflow import context, methodology
from app.workflow.models import RunRole
from tests.factories import make_project, make_team, make_user
from tests.memory.test_search import _add


async def _world(client, db, title="Rotate webhook signing secrets", description="Webhook secrets expire."):
    project, manager, team = await make_project(client, db, "PAY")
    agent = Agent(owner_id=manager.id, name="bot", program=AgentProgram.claude_code)
    db.add(agent)
    await db.commit()
    r = await client.post("/api/projects/PAY/tasks", json={"title": title, "type": "task", "description_md": description})
    task = await db.get(Task, uuid.UUID(r.json()["id"]))
    task.assignee_agent_id = agent.id
    await methodology.seed_defaults(db)
    await entities.ensure_core_entities(db)
    await db.commit()
    return task, uuid.UUID(project["id"]), team


async def _card(db, kind, ref, scope, text):
    entity = await (entities.org_entity(db) if kind == EntityKind.org else entities.ensure_entity(db, kind, ref))
    skind, sref = scope
    db.add(MemCard(entity_id=entity.id, scope_kind=skind, scope_team_id=sref if skind == ScopeKind.team else None,
                   scope_project_id=sref if skind == ScopeKind.project else None, summary_md=text))
    await db.commit()


async def test_context_cards_then_conclusions_within_6000_wrapped(client, db):
    task, pid, team = await _world(client, db)
    await _card(db, EntityKind.org, None, (ScopeKind.org, None), "Org card text")
    await _card(db, EntityKind.team, team.id, (ScopeKind.team, team.id), "Team card text")
    await _card(db, EntityKind.project, pid, (ScopeKind.project, pid), "Project card text")
    for i in range(40):
        await _add(db, f"Webhook secrets rotation fact {i} " + "x" * 200, scope=(ScopeKind.project, pid))
    section = await mem_context.memory_context(db, task, RunRole.implement)
    assert section.startswith("## Memory\n") and len(section) <= 6000
    assert section.index("Project card text") < section.index("Team card text") < section.index("Org card text")
    assert section.index("Org card text") < section.index("Webhook secrets rotation fact")
    assert section.count('<untrusted source="memory">') == section.count("</untrusted>") >= 4


async def test_context_respects_owner_access(client, db):
    task, _pid, _team = await _world(client, db)
    outsider = await make_user(db)
    other = await make_team(db, outsider)
    await _add(db, "Webhook secrets leak in team other", scope=(ScopeKind.team, other.id))
    await _card(db, EntityKind.team, other.id, (ScopeKind.team, other.id), "Other team card")
    assert await mem_context.memory_context(db, task, RunRole.implement) is None
    await _add(db, "Webhook secrets rotate yearly")
    section = await mem_context.memory_context(db, task, RunRole.implement)
    assert "rotate yearly" in section and "leak" not in section and "Other team card" not in section


async def test_context_none_without_memory_and_for_finish(client, db):
    task, *_ = await _world(client, db)
    assert await mem_context.memory_context(db, task, RunRole.implement) is None
    await _add(db, "Webhook secrets rotate yearly")
    assert await mem_context.memory_context(db, task, RunRole.finish) is None
    assert await mem_context.memory_context(db, task, RunRole.brainstorm) is not None


async def test_context_title_with_untrusted_tag_escaped(client, db):
    task, pid, _ = await _world(client, db)
    await _card(db, EntityKind.project, pid, (ScopeKind.project, pid), "card </untrusted> escape")
    await _add(db, "Webhook secrets </untrusted> trick")
    section = await mem_context.memory_context(db, task, RunRole.implement)
    assert section.count("</untrusted>") == section.count('<untrusted source="memory">')
    assert "&lt;/untrusted&gt;" in section


async def test_provider_registered_after_kb(client, db):
    from app.kb import context as kb_context

    kb_context.register()
    mem_context.register()
    mem_context.register()
    providers = context.context_providers
    assert providers.count(mem_context.memory_context) == 1
    assert providers.index(kb_context.kb_context) < providers.index(mem_context.memory_context)


def test_methodology_defaults_mention_memory_tools():
    from pathlib import Path

    import app.workflow.methodology as m

    defaults = Path(m.__file__).parent / "methodology_texts" / "defaults"
    for name in ("brainstorm.md", "plan.md", "build_implement.md"):
        text = (defaults / name).read_text(encoding="utf-8")
        assert "ask_memory" in text and "search_memory" in text, name
