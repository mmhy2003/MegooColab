"""A run stays with the machine it was sent to: another machine of the same person never fails or finishes it."""

import uuid

from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from tests.factories import login, make_project, make_user
from tests.agent_runs.test_dispatch import _run_status, _start, _task, _wait_run
from tests.agent_runs.test_run_guards import _next_of
from tests.runner.test_machines_ws import _all_available, _two_machines
from tests.runner.test_runner_ws import URL, _expect_close, _wait_status


def _run(tc, task, run_id) -> dict:
    return next(r for r in tc.get(f"/api/tasks/{task['key']}/agent-runs").json() if r["id"] == run_id)


async def test_other_machine_hello_does_not_fail_runs(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, yoga, legion, a, _, _ = await _two_machines(db, tc)
    task = _task(tc, a)
    with tc.websocket_connect(URL, headers=yoga["headers"]) as ws_yoga:
        ws_yoga.receive_json()
        ws_yoga.send_json(_all_available(a))
        _wait_status(tc, a["id"], "online")
        run = _start(tc, task)
        assert _next_of(ws_yoga, "run_start")["run_id"] == run["id"]
        with tc.websocket_connect(URL, headers=legion["headers"]) as ws_legion:
            ws_legion.receive_json()
            ws_legion.send_json(_all_available())
            ws_legion.send_json({"type": "heartbeat"})
            _wait_status(tc, a["id"], "busy")
            assert _run_status(tc, task, run["id"]) == "running"


async def test_other_machine_disconnect_leaves_runs_alone(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, yoga, legion, a, _, _ = await _two_machines(db, tc)
    task = _task(tc, a)
    with tc.websocket_connect(URL, headers=yoga["headers"]) as ws_yoga:
        ws_yoga.receive_json()
        ws_yoga.send_json(_all_available(a))
        _wait_status(tc, a["id"], "online")
        run = _start(tc, task)
        _next_of(ws_yoga, "run_start")
        with tc.websocket_connect(URL, headers=legion["headers"]) as ws_legion:
            ws_legion.receive_json()
        # Legion is gone; Yoga still answers, and its run is untouched
        ws_yoga.send_json({"type": "heartbeat"})
        ws_yoga.send_json({"type": "agent_status", "agent_id": a["id"], "available": True, "problems": []})
        _wait_status(tc, a["id"], "busy")
        assert _run_status(tc, task, run["id"]) == "running"


async def test_run_message_from_wrong_machine_is_ignored(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, yoga, legion, a, b, _ = await _two_machines(db, tc)
    task = _task(tc, a)
    with tc.websocket_connect(URL, headers=yoga["headers"]) as ws_yoga:
        ws_yoga.receive_json()
        ws_yoga.send_json(_all_available(a))
        _wait_status(tc, a["id"], "online")
        run = _start(tc, task)
        _next_of(ws_yoga, "run_start")
        with tc.websocket_connect(URL, headers=legion["headers"]) as ws_legion:
            ws_legion.receive_json()
            ws_legion.send_json(
                {"type": "run_finished", "run_id": run["id"], "outcome": "completed", "summary": "not mine"}
            )
            # the socket is still served: its next report is processed
            ws_legion.send_json(_all_available(b))
            _wait_status(tc, b["id"], "online")
            assert _run_status(tc, task, run["id"]) == "running"


async def test_revoking_a_machine_token_cancels_its_runs_only(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, yoga, legion, a, b, _ = await _two_machines(db, tc)
    task_a, task_b = _task(tc, a, title="On Yoga"), _task(tc, b, title="On Legion")
    with tc.websocket_connect(URL, headers=yoga["headers"]) as ws_yoga:
        ws_yoga.receive_json()
        ws_yoga.send_json(_all_available(a))
        with tc.websocket_connect(URL, headers=legion["headers"]) as ws_legion:
            ws_legion.receive_json()
            ws_legion.send_json(_all_available(b))
            _wait_status(tc, a["id"], "online")
            _wait_status(tc, b["id"], "online")
            run_a, run_b = _start(tc, task_a), _start(tc, task_b)
            _next_of(ws_yoga, "run_start")
            _next_of(ws_legion, "run_start")

            assert tc.delete(f"/api/tokens/{yoga['id']}").status_code == 204
            _expect_close(ws_yoga, 4401)
            _wait_run(tc, task_a, run_a["id"], "cancelled")
            assert _run(tc, task_a, run_a["id"])["reason"] == "runner_unauthorized"
            assert _run_status(tc, task_b, run_b["id"]) == "running"
            mine = {x["id"]: x for x in tc.get("/api/agents/mine").json()}
            assert mine[a["id"]]["machine"] is None
            assert mine[b["id"]]["machine"]["name"] == "Legion"


async def test_startup_sweep_fails_running_runs_of_unlinked_agents(db, tc_factory):
    tc = tc_factory(lifespan=True)
    me, _, _, a, _, c = await _two_machines(db, tc)
    task_a, task_c = _task(tc, a, title="Linked"), _task(tc, c, title="Unlinked")
    for task, agent in ((task_a, a), (task_c, c)):
        db.add(AgentRun(task_id=uuid.UUID(task["id"]), agent_id=uuid.UUID(agent["id"]), requested_by=me.id,
                        policy="read_only", status="running", prompt="p"))
    await db.commit()

    from app.agent_runs.service import fail_orphaned_runs

    async with SessionLocal() as s:
        await fail_orphaned_runs(s)
        await s.commit()

    rows = {
        str(r.agent_id): r
        for r in (await db.execute(select(AgentRun).execution_options(populate_existing=True))).scalars()
    }
    assert (rows[c["id"]].status, rows[c["id"]].reason) == ("failed", "runner_disconnected")
    assert rows[a["id"]].status == "running"


async def test_dispatch_follows_the_link_not_a_stale_runner(client, db):
    """Final review I1: right after a relink the old machine may still list the agent until its welcome is
    rebuilt; the database link decides, so the old machine is never sent the agent's run."""
    import json

    from sqlalchemy import update

    from app.agents.models import Agent
    from app.auth.models import TokenScope, User
    from app.auth.tokens import create_token
    from app.runner.registry import registry
    from tests.agent_runs.test_dispatch import _dispatch_in_own_session, _fake_conn, _FakeSocket, _offline_runs

    me, agent, runs = await _offline_runs(client, db)
    sock = _FakeSocket()
    await _fake_conn(me, agent, sock)  # Yoga, still listing the agent as available
    try:
        async with SessionLocal() as s:
            legion, _ = await create_token(s, await s.get(User, me.id), "Legion", [TokenScope.runner], None)
            await s.execute(update(Agent).where(Agent.id == uuid.UUID(agent["id"])).values(runner_token_id=legion.id))
            await s.commit()
        await _dispatch_in_own_session(me.id)
        assert [m for m in map(json.loads, sock.sent) if m["type"] == "run_start"] == []
        row = await db.get(AgentRun, uuid.UUID(runs[0]["id"]), populate_existing=True)
        assert row.status == "queued"
    finally:
        registry._conns.pop(me.id, None)


async def test_relink_waits_for_a_claim_in_progress(client, db):
    """Final review I2: a PATCH racing a dispatch that is claiming a run sees the run once the claim commits."""
    import asyncio

    from sqlalchemy import update

    from app.agents.models import Agent

    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    yoga = (await client.post("/api/tokens", json={"name": "Yoga", "scopes": ["runner"]})).json()["token"]["id"]
    legion = (await client.post("/api/tokens", json={"name": "Legion", "scopes": ["runner"]})).json()["token"]["id"]
    agent = (await client.post("/api/agents", json={"program": "claude_code", "runner_token_id": yoga})).json()
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "T"})).json()
    run = AgentRun(task_id=uuid.UUID(task["id"]), agent_id=uuid.UUID(agent["id"]), requested_by=me.id,
                   policy="read_only", status="queued", prompt="p")
    db.add(run)
    await db.commit()

    async with SessionLocal() as claim:  # the dispatch's claim: the agent row locked, the run marked running
        await claim.execute(
            select(Agent.id).where(Agent.id == uuid.UUID(agent["id"])).with_for_update(key_share=True)
        )
        await claim.execute(update(AgentRun).where(AgentRun.id == run.id).values(status="running"))
        patch = asyncio.create_task(client.patch(f"/api/agents/{agent['id']}", json={"runner_token_id": legion}))
        await asyncio.sleep(0.5)
        await claim.commit()
    r = await patch
    assert r.status_code == 409 and r.json()["detail"] == "agent_running"
