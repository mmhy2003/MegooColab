"""Agents linked to the runner token of the machine they run on (plan 17)."""

import uuid
from datetime import timedelta

from sqlalchemy import update

from app.agent_runs.models import AgentRun
from app.auth.models import PersonalAccessToken, Role
from app.auth.tokens import revoke_user_tokens
from app.auth.service import now
from tests.factories import login, make_project, make_user


async def _token(client, name: str, scopes=("runner", "mcp")) -> str:
    r = await client.post("/api/tokens", json={"name": name, "scopes": list(scopes)})
    assert r.status_code == 201, r.text
    return r.json()["token"]["id"]


async def _agent(client, **body) -> dict:
    body.setdefault("program", "claude_code")
    r = await client.post("/api/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _mine(client, agent_id: str) -> dict:
    return next(a for a in (await client.get("/api/agents/mine")).json() if a["id"] == agent_id)


async def _expire(db, token_id: str) -> None:
    await db.execute(
        update(PersonalAccessToken)
        .where(PersonalAccessToken.id == uuid.UUID(token_id))
        .values(expires_at=now() - timedelta(minutes=1))
    )
    await db.commit()


async def test_create_agent_linked_to_runner_token(client, db):
    me = await make_user(db)
    await login(client, me)
    yoga = await _token(client, "Yoga")
    a = await _agent(client, runner_token_id=yoga)
    assert a["machine"] == {"token_id": yoga, "name": "Yoga", "expired": False}


async def test_new_agent_is_unlinked_by_default(client, db):
    me = await make_user(db)
    await login(client, me)
    await _token(client, "Yoga")
    assert (await _agent(client))["machine"] is None


async def test_link_refuses_foreign_mcp_only_revoked_and_expired_tokens(client, client_factory, db):
    other = await make_user(db)
    other_client = client_factory()
    await login(other_client, other)
    foreign = await _token(other_client, "Theirs")

    me = await make_user(db)
    await login(client, me)
    mcp_only = await _token(client, "MCP", scopes=("mcp",))
    revoked = await _token(client, "Old")
    assert (await client.delete(f"/api/tokens/{revoked}")).status_code == 204
    expired = await _token(client, "Expired")
    await _expire(db, expired)
    agent = await _agent(client)

    for bad in (foreign, mcp_only, revoked, expired, str(uuid.uuid4())):
        r = await client.post("/api/agents", json={"program": "codex", "runner_token_id": bad})
        assert r.status_code == 422 and r.json()["detail"] == "runner_token_invalid", bad
        r = await client.patch(f"/api/agents/{agent['id']}", json={"runner_token_id": bad})
        assert r.status_code == 422 and r.json()["detail"] == "runner_token_invalid", bad


async def test_patch_without_runner_token_id_keeps_link(client, db):
    me = await make_user(db)
    await login(client, me)
    yoga = await _token(client, "Yoga")
    a = await _agent(client, runner_token_id=yoga)

    r = await client.patch(f"/api/agents/{a['id']}", json={"name": "Renamed"})
    assert r.status_code == 200 and r.json()["machine"]["token_id"] == yoga
    r = await client.patch(f"/api/agents/{a['id']}", json={"runner_token_id": None})
    assert r.status_code == 200 and r.json()["machine"] is None


async def test_relink_refused_while_agent_running(client, db):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    yoga = await _token(client, "Yoga")
    legion = await _token(client, "Legion")
    a = await _agent(client, runner_token_id=yoga)
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "T"})).json()
    run = AgentRun(task_id=uuid.UUID(task["id"]), agent_id=uuid.UUID(a["id"]), requested_by=me.id,
                   policy="read_only", status="running", prompt="p")
    db.add(run)
    await db.commit()

    r = await client.patch(f"/api/agents/{a['id']}", json={"runner_token_id": legion})
    assert r.status_code == 409 and r.json()["detail"] == "agent_running"
    r = await client.patch(f"/api/agents/{a['id']}", json={"runner_token_id": None})
    assert r.status_code == 409 and r.json()["detail"] == "agent_running"
    assert (await _mine(client, a["id"]))["machine"]["token_id"] == yoga
    # renaming a busy agent is fine, and so is sending its current link again
    r = await client.patch(f"/api/agents/{a['id']}", json={"name": "Busy", "runner_token_id": yoga})
    assert r.status_code == 200

    await db.execute(update(AgentRun).where(AgentRun.id == run.id).values(status="queued"))
    await db.commit()
    r = await client.patch(f"/api/agents/{a['id']}", json={"runner_token_id": legion})
    assert r.status_code == 200 and r.json()["machine"]["name"] == "Legion"


async def test_expired_token_keeps_link_and_reports_expired(client, db):
    me = await make_user(db)
    await login(client, me)
    yoga = await _token(client, "Yoga")
    a = await _agent(client, runner_token_id=yoga)
    await _expire(db, yoga)
    assert (await _mine(client, a["id"]))["machine"] == {"token_id": yoga, "name": "Yoga", "expired": True}


async def test_revoking_token_unlinks_only_its_agents(client, db):
    me = await make_user(db)
    await login(client, me)
    yoga = await _token(client, "Yoga")
    legion = await _token(client, "Legion")
    a = await _agent(client, runner_token_id=yoga)
    b = await _agent(client, program="codex", runner_token_id=legion)

    assert (await client.delete(f"/api/tokens/{yoga}")).status_code == 204
    assert (await _mine(client, a["id"]))["machine"] is None
    assert (await _mine(client, b["id"]))["machine"]["token_id"] == legion


async def test_bulk_revoke_unlinks_every_agent(client, client_factory, db):
    other = await make_user(db)
    other_client = client_factory()
    await login(other_client, other)
    theirs = await _agent(other_client, runner_token_id=await _token(other_client, "Theirs"))

    me = await make_user(db)
    await login(client, me)
    a = await _agent(client, runner_token_id=await _token(client, "Yoga"))
    b = await _agent(client, program="codex", runner_token_id=await _token(client, "Legion"))

    await revoke_user_tokens(db, me.id)
    await db.commit()
    for agent_id in (a["id"], b["id"]):
        assert (await _mine(client, agent_id))["machine"] is None
    assert (await _mine(other_client, theirs["id"]))["machine"] is not None


async def test_machine_shown_only_to_owner_and_admin(client, client_factory, db):
    me = await make_user(db)
    teammate = await make_user(db)
    await make_project(client, db, "PAY", me, teammate)
    await login(client, me)
    a = await _agent(client, runner_token_id=await _token(client, "Yoga"))
    r = await client.put(f"/api/agents/{a['id']}/bindings",
                         json={"bindings": [{"project_ref": "PAY", "local_path": "/repo"}]})
    assert r.status_code == 200
    assert (await _mine(client, a["id"]))["machine"]["name"] == "Yoga"

    mate = client_factory()
    await login(mate, teammate)
    seen = next(x for x in (await mate.get("/api/projects/PAY/agents")).json() if x["id"] == a["id"])
    assert seen["machine"] is None

    admin = client_factory()
    await login(admin, await make_user(db, role=Role.admin))
    seen = next(x for x in (await admin.get("/api/admin/agents")).json() if x["id"] == a["id"])
    assert seen["machine"]["name"] == "Yoga"


async def test_token_list_shows_linked_agents(client, db):
    me = await make_user(db)
    await login(client, me)
    yoga = await _token(client, "Yoga")
    legion = await _token(client, "Legion")
    a = await _agent(client, name="Yoga Claude", runner_token_id=yoga)
    tokens = {t["id"]: t for t in (await client.get("/api/tokens")).json()}
    assert tokens[yoga]["agents"] == [{"id": a["id"], "name": "Yoga Claude"}]
    assert tokens[legion]["agents"] == []
