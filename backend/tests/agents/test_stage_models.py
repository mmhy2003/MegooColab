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


# ---- runs get their stage's model (Task 4) -------------------------------------------------------------------

import uuid  # noqa: E402

from app.agent_runs.models import AgentRun  # noqa: E402
from app.agents.models import Agent  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.workflow.models import RunRole  # noqa: E402
from tests.agent_runs.test_dispatch import _setup, _start  # noqa: E402
from tests.runner.test_protocol_v2 import _hello_v2, _make_workflow  # noqa: E402
from tests.runner.test_runner_ws import URL, _manager_with_project, _wait_status  # noqa: E402

CURRENT = ("workflow/1", "branch/1", "model/1", "stagemodel/1")


def test_each_role_maps_to_its_row():
    from app.agents.stage_models import row_for

    rows = {role: row_for(role) for role in RunRole}
    assert rows == {
        RunRole.brainstorm: "design", RunRole.plan: "plan",
        RunRole.implement: "build", RunRole.step_fix: "build", RunRole.final_fix: "build", RunRole.pr_fix: "build",
        RunRole.step_review: "review", RunRole.final_review: "review", RunRole.pr_review: "review",
        RunRole.finish: "finish", RunRole.freestyle: None,
    }


def test_run_model_resolution():
    from app.agents.stage_models import overriding_roles, run_model

    rows = {"design": {"model": "fable", "effort": "max"}, "plan": {"model": "fable"}, "build": {"effort": "low"}}
    agent = Agent(model="opus", effort="high", stage_models=rows)

    def pick(role):
        c = run_model(agent, role)
        return c and (c.model, c.effort)

    assert pick(RunRole.brainstorm) == ("fable", "max")
    assert pick(RunRole.plan) == ("fable", "")  # the row's model with its own default effort
    assert pick(RunRole.step_fix) == ("opus", "low")
    assert pick(RunRole.final_review) == ("opus", "high")
    assert pick(RunRole.freestyle) is None
    assert run_model(Agent(model="opus", effort="high", stage_models={}), RunRole.plan) is None
    on_default = Agent(model=None, effort=None, stage_models={"plan": {"model": "fable"}})
    assert (run_model(on_default, RunRole.step_review).model, run_model(on_default, RunRole.step_review).effort) == ("", "")
    assert overriding_roles(agent) == {RunRole.brainstorm, RunRole.plan, RunRole.implement, RunRole.step_fix,
                                       RunRole.final_fix, RunRole.pr_fix}


async def _with_stages(agent_id: str, rows: dict) -> None:
    async with SessionLocal() as s:
        (await s.get(Agent, uuid.UUID(agent_id))).stage_models = rows
        await s.commit()


async def test_run_start_carries_the_stages_model(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    await _with_stages(agent["id"], {"plan": {"model": "fable"}})
    run = _start(tc, task)
    await _make_workflow(db, run["id"], role="plan")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent, capabilities=CURRENT))
        start = ws.receive_json()
        assert start["run_id"] == run["id"] and start["model_choice"] == {"model": "fable", "effort": ""}


async def test_no_rows_no_model_choice(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    await _make_workflow(db, run["id"], role="plan")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent, capabilities=CURRENT))
        start = ws.receive_json()
        assert start["run_id"] == run["id"] and start["model_choice"] is None


async def test_an_older_runner_leaves_only_overridden_stages_queued(db, tc_factory):
    from app.runner.registry import STAGE_MODEL_PROBLEM

    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    await _with_stages(agent["id"], {"plan": {"model": "fable"}})
    held = _start(tc, task)
    await _make_workflow(db, held["id"], role="plan")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent))
        _wait_status(tc, agent["id"], "online")
        mine = next(a for a in tc.get("/api/agents/mine").json() if a["id"] == agent["id"])
        assert STAGE_MODEL_PROBLEM in mine["problems"]
        assert STAGE_MODEL_PROBLEM == "runner too old to choose a model per stage — update megoocolab-runner"
        async with SessionLocal() as s:
            assert (await s.get(AgentRun, uuid.UUID(held["id"]))).status == "queued"
    # an implement run (its row unset) still goes to the older runner, as before
    async with SessionLocal() as s:
        (await s.get(AgentRun, uuid.UUID(held["id"]))).status = "cancelled"
        await s.commit()
    other = _start(tc, task)
    await _make_workflow(db, other["id"], role="implement")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent))
        start = ws.receive_json()
        assert start["run_id"] == other["id"] and start.get("model_choice") is None


async def test_clearing_the_stages_still_puts_a_continued_session_back(db, tc_factory):
    """A session an earlier run put on a stage's model goes back to the agent's own even after the owner cleared
    every stage (final review)."""
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    earlier = _start(tc, task)
    await _make_workflow(db, earlier["id"], role="brainstorm")
    async with SessionLocal() as s:
        row = await s.get(AgentRun, uuid.UUID(earlier["id"]))
        row.status, row.session_ref, row.model_choice = "completed", "sess-1", {"model": "fable", "effort": ""}
        await s.commit()
    run = _start(tc, task)  # no stages set any more
    await _make_workflow(db, run["id"], role="brainstorm", resume_session_ref="sess-1")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent, capabilities=CURRENT))
        start = ws.receive_json()
        assert start["run_id"] == run["id"]
        assert start["model_choice"] == {"model": agent["model"] or "", "effort": ""}
        # read while connected: the server commits the start after sending it
        assert await _kept_choice(run["id"]) == start["model_choice"]


async def test_the_choice_sent_is_kept_on_the_run(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    await _with_stages(agent["id"], {"plan": {"model": "fable"}})
    run = _start(tc, task)
    await _make_workflow(db, run["id"], role="plan")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent, capabilities=CURRENT))
        assert ws.receive_json()["run_id"] == run["id"]
        assert await _kept_choice(run["id"]) == {"model": "fable", "effort": ""}


async def _kept_choice(run_id: str):
    """The choice stored on the run, once the server has committed the start (it commits after the send)."""
    import asyncio

    for _ in range(50):
        async with SessionLocal() as s:
            choice = (await s.get(AgentRun, uuid.UUID(run_id))).model_choice
        if choice is not None:
            return choice
        await asyncio.sleep(0.05)
    return None
