"""An agent's default model: chosen by its owner, sent in the welcome, applied by a runner with model/1, and the
models the agent offers, reported by the runner."""

import uuid

from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.agent_runs.service import apply_update, sanitize_update
from app.agents.models import Agent
from app.audit.models import AuditLog
from app.auth.models import Role
from app.core.db import SessionLocal
from app.runner.registry import MODEL_PROBLEM
from app.runner.router import build_welcome
from app.tasks.models import TaskEvent
from tests.agent_runs.test_dispatch import _avail, _setup, _start, _wait_run
from tests.a2a.test_models import _question, _question_run, _world
from tests.agent_runs.test_updates import _running
from tests.factories import login, make_user
from tests.runner.test_runner_ws import URL, _hello, _manager_with_project, _wait_status


async def _agent(client, **body):
    r = await client.post("/api/agents", json={"program": "claude_code", **body})
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_new_agent_starts_on_its_programs_default_model(client, db):
    await login(client, await make_user(db))
    claude = await _agent(client, name="C")
    codex = await _agent(client, name="X", program="codex")
    assert (claude["model"], codex["model"]) == ("Opus 5.5", "GPT-6.1 Sol")
    assert claude["known_models"] == []
    # asked for none: the program's own default
    assert (await _agent(client, name="N", model=None))["model"] is None


async def test_the_model_is_set_on_create_changed_and_cleared(client, db):
    me = await make_user(db)
    await login(client, me)
    agent = await _agent(client, model="  opus ")
    assert agent["model"] == "opus"
    r = await client.patch(f"/api/agents/{agent['id']}", json={"model": "sonnet"})
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "sonnet"
    # a name-only change leaves it
    assert (await client.patch(f"/api/agents/{agent['id']}", json={"name": "Claude 2"})).json()["model"] == "sonnet"
    for cleared in (None, "", "   "):
        await client.patch(f"/api/agents/{agent['id']}", json={"model": "sonnet"})
        assert (await client.patch(f"/api/agents/{agent['id']}", json={"model": cleared})).json()["model"] is None
    entries = (await db.execute(select(AuditLog).where(AuditLog.action == "agent.model_changed"))).scalars().all()
    assert {"model": "sonnet", "effort": None} in [e.data for e in entries]


async def test_a_model_name_too_long_is_refused_and_nul_is_dropped(client, db):
    await login(client, await make_user(db))
    agent = await _agent(client)
    assert (await client.patch(f"/api/agents/{agent['id']}", json={"model": "x" * 101})).status_code == 422
    assert (await client.patch(f"/api/agents/{agent['id']}", json={"model": "op\x00us"})).json()["model"] == "opus"


async def test_the_welcome_carries_the_model(client, db):
    me = await make_user(db)
    await login(client, me)
    token = (await client.post("/api/tokens", json={"name": "laptop", "scopes": ["runner"]})).json()["token"]
    await _agent(client, name="A", model="opus", runner_token_id=token["id"])
    await _agent(client, name="B", model=None, runner_token_id=token["id"])
    welcome = await build_welcome(me.id, uuid.UUID(token["id"]))
    assert [(a.name, a.model) for a in welcome.agents] == [("A", "opus"), ("B", None)]
    assert welcome.model_dump(mode="json")["agents"][1]["model"] is None


def test_model_reports_are_cut_to_their_limits():
    options = [{"value": f"m{i}", "name": "N" * 300, "secret": "x"} for i in range(60)] + ["junk", {"name": "no value"}]
    clean = sanitize_update("model_options", {"options": options, "extra": 1})
    assert len(clean["options"]) == 50
    assert clean["options"][0] == {"value": "m0", "name": "N" * 100, "efforts": []}
    assert sanitize_update("model", {"value": "opus", "name": "Opus\x00 4", "x": 1}) == {"value": "opus", "name": "Opus 4"}


async def test_the_models_an_agent_offers_are_kept_for_its_owner(client, db):
    me, agent, [run_id] = await _running(client, db)
    options = [{"value": "default", "name": "Default (recommended)"}, {"value": "opus", "name": "Opus"}]
    await apply_update(db, me.id, run_id, 1, "model_options", {"options": options})
    await db.commit()
    mine = next(a for a in (await client.get("/api/agents/mine")).json() if a["id"] == agent["id"])
    assert mine["known_models"] == [{**o, "efforts": []} for o in options]
    # not a progress event
    kinds = (await db.execute(select(TaskEvent.kind))).scalars().all()
    assert "agent_model_options" not in kinds
    # someone else seeing the agent does not get its owner's list
    other = await make_user(db, role=Role.admin)
    await login(client, other)
    seen = next(a for a in (await client.get("/api/admin/agents")).json() if a["id"] == agent["id"])
    assert seen["known_models"] == []


async def test_the_model_a_run_uses_shows_in_activity(client, db):
    me, agent, [run_id] = await _running(client, db)
    await apply_update(db, me.id, run_id, 1, "model", {"value": "opus", "name": "Opus 4.7"})
    await db.commit()
    task_key = (await client.get("/api/projects/PAY/tasks")).json()[0]["key"]
    items = (await client.get(f"/api/tasks/{task_key}/activity")).json()
    ev = next(i for i in items if i["kind"] == "agent_model")
    assert ev["data"] == {"value": "opus", "name": "Opus 4.7", "run_id": str(run_id), "agent_id": agent["id"]}


async def test_an_answering_run_still_reports_the_models(client, db):
    me, pid, agent = await _world(client, db)
    q = await _question(db, pid, me)
    run = _question_run(q, agent, me, status="running")
    db.add(run)
    await db.commit()
    async with SessionLocal() as s:
        await apply_update(s, me.id, run.id, 1, "model_options", {"options": [{"value": "opus", "name": "Opus"}]})
        await s.commit()
    async with SessionLocal() as s:
        assert (await s.get(Agent, uuid.UUID(agent["id"]))).known_models == [{"value": "opus", "name": "Opus", "efforts": []}]


async def test_a_runner_without_model_support_leaves_runs_of_an_agent_with_a_model_queued(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    assert agent["model"] == "Opus 5.5"  # a new agent's default model needs model/1 too
    run = _start(tc, task, prompt="Go")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)], capabilities=["workflow/1", "branch/1"]))
        _wait_status(tc, agent["id"], "online")
        mine = next(a for a in tc.get("/api/agents/mine").json() if a["id"] == agent["id"])
        assert mine["problems"] == [MODEL_PROBLEM]
        assert MODEL_PROBLEM == "runner too old to choose the model — update megoocolab-runner"
        async with SessionLocal() as s:
            assert (await s.get(AgentRun, uuid.UUID(run["id"]))).status == "queued"
        ws.send_json(_hello([_avail(agent)], capabilities=["workflow/1", "branch/1", "model/1"]))
        start = ws.receive_json()
        assert start["run_id"] == run["id"]


async def test_without_a_model_an_older_runner_still_takes_runs(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    assert tc.patch(f"/api/agents/{agent['id']}", json={"model": None}).json()["model"] is None
    run = _start(tc, task, prompt="Go")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)], capabilities=["workflow/1", "branch/1"]))
        assert ws.receive_json()["run_id"] == run["id"]
        mine = next(a for a in tc.get("/api/agents/mine").json() if a["id"] == agent["id"])
        assert MODEL_PROBLEM not in mine["problems"]


async def test_model_unavailable_is_kept_as_the_runs_reason(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task, prompt="Go")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        ws.receive_json()
        ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "failed", "summary": "",
                      "error": "model_unavailable"})
        _wait_run(tc, task, run["id"], "failed")
    async with SessionLocal() as s:
        assert (await s.get(AgentRun, uuid.UUID(run["id"]))).reason == "model_unavailable"


async def test_effort_is_set_with_the_model_and_cleared_on_its_own(client, db):
    await login(client, await make_user(db))
    agent = await _agent(client, effort=" High ")
    assert (agent["model"], agent["effort"]) == ("Opus 5.5", "High")
    assert (await _agent(client, name="N"))["effort"] is None  # the model's own default
    r = await client.patch(f"/api/agents/{agent['id']}", json={"model": "sonnet", "effort": "low"})
    assert (r.json()["model"], r.json()["effort"]) == ("sonnet", "low")
    assert (await client.patch(f"/api/agents/{agent['id']}", json={"effort": ""})).json()["effort"] is None
    assert (await client.patch(f"/api/agents/{agent['id']}", json={"effort": "x" * 41})).status_code == 422
    entries = (await db.execute(select(AuditLog).where(AuditLog.action == "agent.model_changed"))).scalars().all()
    assert {"model": "sonnet", "effort": "low"} in [e.data for e in entries]


async def test_the_welcome_carries_the_effort(client, db):
    me = await make_user(db)
    await login(client, me)
    token = (await client.post("/api/tokens", json={"name": "laptop", "scopes": ["runner"]})).json()["token"]
    await _agent(client, name="A", effort="max", runner_token_id=token["id"])
    welcome = await build_welcome(me.id, uuid.UUID(token["id"]))
    assert welcome.model_dump(mode="json")["agents"][0]["effort"] == "max"


def test_each_models_effort_levels_are_kept_within_limits():
    efforts = [{"value": f"e{i}", "name": "E" * 80} for i in range(15)] + ["junk", {"name": "no value"}]
    clean = sanitize_update("model_options", {"options": [{"value": "opus", "name": "Opus", "efforts": efforts}]})
    [opus] = clean["options"]
    assert len(opus["efforts"]) == 10
    assert opus["efforts"][0] == {"value": "e0", "name": "E" * 40}
    # a model without effort levels has none
    assert sanitize_update("model_options", {"options": [{"value": "haiku", "name": "Haiku"}]})["options"] == [
        {"value": "haiku", "name": "Haiku", "efforts": []}
    ]
    used = {"value": "opus", "name": "Opus 5.5", "effort": "high", "effort_name": "High", "x": 1}
    assert sanitize_update("model", used) == {k: v for k, v in used.items() if k != "x"}


async def test_an_effort_alone_also_needs_a_runner_that_can_choose(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    tc.patch(f"/api/agents/{agent['id']}", json={"model": None, "effort": "high"})
    run = _start(tc, task, prompt="Go")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)], capabilities=["workflow/1", "branch/1"]))
        _wait_status(tc, agent["id"], "online")
        mine = next(a for a in tc.get("/api/agents/mine").json() if a["id"] == agent["id"])
        assert mine["problems"] == [MODEL_PROBLEM]
        async with SessionLocal() as s:
            assert (await s.get(AgentRun, uuid.UUID(run["id"]))).status == "queued"


async def test_effort_unavailable_is_kept_as_the_runs_reason(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task, prompt="Go")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        ws.receive_json()
        ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "failed", "summary": "",
                      "error": "effort_unavailable"})
        _wait_run(tc, task, run["id"], "failed")
    async with SessionLocal() as s:
        assert (await s.get(AgentRun, uuid.UUID(run["id"]))).reason == "effort_unavailable"
