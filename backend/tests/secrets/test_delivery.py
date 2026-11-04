"""Secrets reach a run: the agent owner's and the run's project's, in run_start, and by name only in its prompt."""

import json
import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunPolicy, RunStatus
from app.agent_runs.service import dispatch_pending
from app.audit.models import AuditLog
from app.core.db import SessionLocal
from app.kb_drafts.models import KbDraft
from app.runner.registry import DRAFTS_CAPABILITY, SECRETS_CAPABILITY, registry
from app.secrets.delivery import prompt_section
from tests.agent_runs.test_dispatch import _fake_conn, _FakeSocket
from tests.chats import helpers as chats
from tests.factories import login
from tests.kb_drafts.conftest import idle
from tests.kb_drafts.conftest import start as start_draft

VALUES = ("owner-a-value", "owner-shared-value", "project-shared-value", "project-b-value", "manager-only-value")


async def _add(client, base: str, name: str, value: str) -> None:
    r = await client.post(base, json={"name": name, "description": f"What {name} is", "value": value})
    assert r.status_code == 201, r.text


async def _dispatch(user, agent: dict, *, caps=(SECRETS_CAPABILITY, DRAFTS_CAPABILITY)) -> list[dict]:
    sock = _FakeSocket()
    conn = await _fake_conn(user, agent, sock)
    conn.capabilities.update(caps)
    try:
        async with SessionLocal() as s:
            await dispatch_pending(s, user.id)
    finally:
        registry._conns.pop(user.id, None)
    return [m for m in map(json.loads, sock.sent) if m["type"] == "run_start"]


async def _chat_world(client, db):
    w = await chats.world(client, db)
    await _add(client, "/api/secrets", "A", "owner-a-value")
    await _add(client, "/api/secrets", "SHARED", "owner-shared-value")
    await login(client, w.manager)
    await _add(client, "/api/projects/PAY/secrets", "SHARED", "project-shared-value")
    await _add(client, "/api/projects/PAY/secrets", "B", "project-b-value")
    await _add(client, "/api/secrets", "MGR_ONLY", "manager-only-value")
    # the manager starts a chat on the owner's agent: the requester is the manager
    await chats.start(client, agent_id=w.agent["id"])
    return w


async def test_run_gets_owner_and_project_secrets_project_wins(client, db):
    w = await _chat_world(client, db)
    [start] = await _dispatch(w.owner, w.agent)
    assert start["secrets"] == [
        {"name": "A", "value": "owner-a-value"},
        {"name": "B", "value": "project-b-value"},
        {"name": "SHARED", "value": "project-shared-value"},
    ]


async def test_requester_personal_secrets_never_go(client, db):
    w = await _chat_world(client, db)
    [start] = await _dispatch(w.owner, w.agent)
    assert "MGR_ONLY" not in json.dumps(start) and "manager-only-value" not in json.dumps(start)


async def test_prompt_section_lists_names_never_values(client, db):
    w = await _chat_world(client, db)
    [start] = await _dispatch(w.owner, w.agent)
    assert "## Secrets you can use" in start["prompt"] and "- B — What B is" in start["prompt"]
    assert "Commands in this read-only session cannot use them." in start["prompt"]  # brainstorm only reads
    stored = (await db.execute(select(AgentRun.prompt))).scalars().all()
    for text in [start["prompt"], *stored]:
        assert not any(v in text for v in VALUES)


def test_workspace_and_read_only_sections_differ():
    secrets = [("TOKEN", "An API token", "value-1234")]
    workspace = prompt_section(secrets, RunPolicy.workspace)
    read_only = prompt_section(secrets, RunPolicy.read_only)
    assert "`$NAME` (bash), `$env:NAME` (PowerShell), `%NAME%` (cmd)" in workspace
    assert "Commands in this read-only session cannot use them." in read_only
    assert "- TOKEN — An API token" in workspace and "value-1234" not in workspace + read_only
    assert prompt_section([], RunPolicy.workspace) == ""


async def test_runner_without_capability_gets_no_secrets_and_no_section(client, db):
    w = await _chat_world(client, db)
    [start] = await _dispatch(w.owner, w.agent, caps=())
    assert "secrets" not in start or start["secrets"] == []
    assert "## Secrets you can use" not in start["prompt"]


async def test_read_only_draft_run_gets_the_read_only_section(client, db, world):
    await _add(client, "/api/secrets", "MY_TOKEN", "my-token-value")
    await start_draft(client, world)
    [start] = await _dispatch(world.me, {"id": str(world.laptop.id)})
    assert start["secrets"] == [{"name": "MY_TOKEN", "value": "my-token-value"}]
    assert "Commands in this read-only session cannot use them." in start["prompt"]


async def test_resumed_run_gets_the_section_in_resume_prompt(client, db, world):
    await _add(client, "/api/secrets", "MY_TOKEN", "my-token-value")
    draft = await start_draft(client, world)
    await idle(db, draft["id"])
    await db.execute(update(KbDraft).where(KbDraft.id == uuid.UUID(draft["id"])).values(session_ref="s1"))
    await db.commit()
    await client.post(f"/api/kb/drafts/{draft['id']}/requests", json={"text": "shorten it"})
    [start] = await _dispatch(world.me, {"id": str(world.laptop.id)})
    assert "## Secrets you can use" in start["resume_prompt"] and "my-token-value" not in start["resume_prompt"]


async def test_team_draft_gets_personal_only(client, db, world):
    await _add(client, "/api/secrets", "MY_TOKEN", "my-token-value")
    await login(client, world.manager)
    await _add(client, "/api/projects/PAY/secrets", "PROJECT_ONLY", "project-only-value")
    await login(client, world.me)
    await start_draft(client, world, space_id=str(world.team_space.id), agent_id=str(world.laptop.id))
    [start] = await _dispatch(world.me, {"id": str(world.laptop.id)})
    assert [s["name"] for s in start["secrets"]] == ["MY_TOKEN"]


async def test_delivery_is_audited_without_values(client, db):
    w = await _chat_world(client, db)
    await _dispatch(w.owner, w.agent)
    [row] = (await db.execute(select(AuditLog).where(AuditLog.action == "secret.delivered"))).scalars().all()
    assert row.data["names"] == ["A", "B", "SHARED"] and not any(v in json.dumps(row.data) for v in VALUES)
    assert (await db.execute(select(AgentRun.status))).scalar() == RunStatus.running


async def test_outdated_agents_lists_old_runners(client, db, world):
    sock = _FakeSocket()
    await _fake_conn(world.me, {"id": str(world.laptop.id)}, sock)  # online, without secrets/1
    try:
        mine = (await client.get("/api/secrets/outdated-agents")).json()
        project = (await client.get("/api/secrets/outdated-agents", params={"project": "PAY"})).json()
    finally:
        registry._conns.pop(world.me.id, None)
    assert sorted(a["name"] for a in mine) == ["home-bot", "laptop-claude"]  # offline machines count by their last hello
    assert sorted(a["name"] for a in project) == ["laptop-claude", "mgr-bot"]

