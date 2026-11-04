import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import update

from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunStatus
from app.agents.models import Agent, AgentBinding
from app.auth.models import User
from app.kb import access
from app.kb.models import KbSpace
from tests.factories import login, make_project, make_team, make_user


@dataclass
class World:
    me: User
    manager: User
    other: User
    project: dict
    space: KbSpace
    team_space: KbSpace
    laptop: Agent  # mine, bound to PAY
    home: Agent  # mine, bound nowhere
    mgr_bot: Agent  # the manager's, bound to PAY


async def _agent(db, owner: User, name: str, project_id: str | None) -> Agent:
    agent = Agent(owner_id=owner.id, name=name, program="claude_code")
    db.add(agent)
    await db.flush()
    if project_id:
        db.add(AgentBinding(agent_id=agent.id, project_id=uuid.UUID(project_id), local_path="/work/pay"))
    await db.commit()
    return agent


@pytest.fixture
async def world(client, db) -> World:
    me = await make_user(db, name="Mia Member")
    other = await make_user(db, name="Otto Other")
    project, manager, _ = await make_project(client, db, "PAY", me, other)
    team = await make_team(db, me, name="Docs")
    space = await access.space_for_project(db, project["id"])
    team_space = await access.space_for_team(db, team.id)
    await db.commit()
    laptop = await _agent(db, me, "laptop-claude", project["id"])
    home = await _agent(db, me, "home-bot", None)
    mgr_bot = await _agent(db, manager, "mgr-bot", project["id"])
    await login(client, me)
    return World(me, manager, other, project, space, team_space, laptop, home, mgr_bot)


async def start(client, w: World, **body) -> dict:
    payload = {"space_id": str(w.space.id), "agent_id": str(w.laptop.id), "brief": "A deploy runbook", "sources": []}
    payload.update(body)
    r = await client.post("/api/kb/drafts", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


async def idle(db, draft_id: str) -> None:
    """Ends the draft's agent turn, as if the agent had finished: the person may edit and save again."""
    await db.execute(
        update(AgentRun)
        .where(AgentRun.draft_id == uuid.UUID(draft_id), AgentRun.status.in_(ACTIVE_STATUSES))
        .values(status=RunStatus.completed)
    )
    await db.commit()
