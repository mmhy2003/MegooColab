import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agent_runs.models import AgentRun
from app.agents.models import Agent
from app.core.db import SessionLocal
from app.kb import access
from app.kb.models import KbDocument
from app.kb_drafts.models import KbDraft
from tests.factories import login, make_project, make_user


async def _setup(client, db):
    user = await make_user(db)
    project, _, _ = await make_project(client, db, "PAY", user)
    space = await access.space_for_project(db, project["id"])
    agent = Agent(owner_id=user.id, name="laptop-claude", program="claude_code")
    doc = KbDocument(id=uuid.uuid4(), space_id=space.id, title="Runbook", body_md="text", latest_revision=1)
    db.add_all([agent, doc])
    await db.commit()
    return user, project, space, agent, doc


def _draft(user, space, agent, doc=None) -> KbDraft:
    return KbDraft(user_id=user.id, agent_id=agent.id, space_id=space.id, document_id=doc.id if doc else None,
                   brief="A runbook", sources=[])


async def test_draft_run_needs_exactly_one_target(client, db):
    user, project, space, agent, _ = await _setup(client, db)
    draft = _draft(user, space, agent)
    db.add(draft)
    await db.commit()
    base = {"draft_id": draft.id, "agent_id": agent.id, "policy": "read_only", "prompt": "p"}
    await login(client, user)
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "t"})).json()

    async with SessionLocal() as s:
        s.add(AgentRun(task_id=uuid.UUID(task["id"]), **base))
        with pytest.raises(IntegrityError):
            await s.commit()
    async with SessionLocal() as s:
        s.add(AgentRun(**base))
        await s.commit()


async def test_one_draft_per_person_per_document(client, db):
    user, _, space, agent, doc = await _setup(client, db)
    db.add_all([_draft(user, space, agent), _draft(user, space, agent)])
    await db.commit()  # two new-document drafts are fine

    db.add(_draft(user, space, agent, doc))
    await db.commit()
    db.add(_draft(user, space, agent, doc))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_deleting_the_document_deletes_its_drafts(client, db):
    user, _, space, agent, doc = await _setup(client, db)
    db.add(_draft(user, space, agent, doc))
    await db.commit()
    await db.delete(doc)
    await db.commit()
    db.expire_all()
    assert (await db.execute(select(KbDraft))).scalars().all() == []
