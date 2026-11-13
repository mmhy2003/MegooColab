"""A model and effort for each workflow stage, on the agent (spec 2026-11-13-stage-models-design)."""

from sqlalchemy import select

from app.audit.models import AuditLog
from tests.factories import login, make_user


async def _agent(client, **body):
    r = await client.post("/api/agents", json={"program": "claude_code", **body})
    assert r.status_code == 201, r.text
    return r.json()


async def test_stage_models_start_empty(client, db):
    await login(client, await make_user(db))
    assert (await _agent(client, name="C"))["stage_models"] == {}


async def test_stage_models_are_set_replaced_and_cleared(client, db):
    await login(client, await make_user(db))
    agent = await _agent(client, name="C")
    url = f"/api/agents/{agent['id']}"
    rows = {"design": {"model": "fable", "effort": "max"}, "plan": {"effort": "high"}, "build": {}}
    r = await client.patch(url, json={"stage_models": rows})
    assert r.status_code == 200, r.text
    want = {"design": {"model": "fable", "effort": "max"}, "plan": {"model": None, "effort": "high"}}
    assert r.json()["stage_models"] == want
    mine = next(a for a in (await client.get("/api/agents/mine")).json() if a["id"] == agent["id"])
    assert mine["stage_models"] == want
    # a name-only change leaves them; blank names are unset
    assert (await client.patch(url, json={"name": "C2"})).json()["stage_models"] == want
    r = await client.patch(url, json={"stage_models": {"review": {"model": "  ", "effort": " low "}}})
    assert r.json()["stage_models"] == {"review": {"model": None, "effort": "low"}}
    assert (await client.patch(url, json={"stage_models": {}})).json()["stage_models"] == {}
    entries = (await db.execute(select(AuditLog).where(AuditLog.action == "agent.model_changed"))).scalars().all()
    stages = [e.data["stage_models"] for e in entries if "stage_models" in e.data]
    assert stages == [
        {"design": {"model": "fable", "effort": "max"}, "plan": {"effort": "high"}},
        {"review": {"effort": "low"}},
        {},
    ]


async def test_unknown_stage_or_long_names_are_refused(client, db):
    await login(client, await make_user(db))
    agent = await _agent(client, name="C")
    url = f"/api/agents/{agent['id']}"
    assert (await client.patch(url, json={"stage_models": {"deploy": {"model": "x"}}})).status_code == 422
    assert (await client.patch(url, json={"stage_models": {"plan": {"model": "m" * 101}}})).status_code == 422
    assert (await client.patch(url, json={"stage_models": {"plan": {"effort": "e" * 41}}})).status_code == 422


async def test_only_the_owner_changes_stage_models(client, db, client_factory):
    await login(client, await make_user(db))
    agent = await _agent(client, name="C")
    other = client_factory()
    await login(other, await make_user(db))
    r = await other.patch(f"/api/agents/{agent['id']}", json={"stage_models": {"plan": {"model": "fable"}}})
    assert r.status_code == 404
