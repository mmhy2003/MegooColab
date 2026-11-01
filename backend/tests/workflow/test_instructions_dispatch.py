"""Waiting messages for the agent go out with its next run: in the prompt, or in the resume prompt."""

import json
import uuid

from sqlalchemy import update

from app.agent_runs.models import AgentRun
from app.agent_runs.service import _send_start, apply_update, dispatch_pending, finish_run
from app.core.db import SessionLocal
from app.runner.registry import registry
from tests.agent_runs.test_dispatch import _claim, _fake_conn, _FakeSocket, _offline_runs


async def _message(client, task_key, body):
    r = await client.post(f"/api/tasks/{task_key}/comments", json={"body_md": body, "to_agent": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _state(client, task_key, cid):
    items = (await client.get(f"/api/tasks/{task_key}/activity")).json()
    return next(i for i in items if i["id"] == cid)["to_agent"]


async def _dispatch(me, agent, sock=None):
    sock = sock or _FakeSocket()
    await _fake_conn(me, agent, sock)
    try:
        async with SessionLocal() as s:
            await dispatch_pending(s, me.id)
            await s.commit()
    finally:
        registry._conns.pop(me.id, None)
    starts = [m for m in map(json.loads, sock.sent) if m["type"] == "run_start"]
    return starts[0] if starts else None


async def _world(client, db, **run_fields):
    me, agent, runs = await _offline_runs(client, db)
    run_id = uuid.UUID(runs[0]["id"])
    if run_fields:
        await db.execute(update(AgentRun).where(AgentRun.id == run_id).values(**run_fields))
        await db.commit()
    return me, agent, run_id, "PAY-1"


async def test_waiting_message_goes_into_the_next_run_start(client, db):
    me, agent, run_id, key = await _world(client, db, workflow_role="plan", stage="plan")
    cid = await _message(client, key, "Log retries")
    assert (await _state(client, key, cid))["state"] == "waiting"  # the run is queued: nothing to steer
    start = await _dispatch(me, agent)
    assert "## New instructions" in start["prompt"] and "> Log retries" in start["prompt"]
    state = await _state(client, key, cid)
    assert state["state"] == "given_at_start" and state["stage"] == "plan"


async def test_resumed_run_gets_it_in_the_resume_prompt(client, db):
    me, agent, run_id, key = await _world(
        client, db, workflow_role="plan", stage="plan", resume_session_ref="sess-1", resume_prompt="Carry on"
    )
    await _message(client, key, "Log retries")
    start = await _dispatch(me, agent)
    assert start["resume_prompt"].startswith("Carry on\n\n## New instructions") and "> Log retries" in start["resume_prompt"]
    assert "Log retries" not in start["prompt"]


async def test_message_written_while_run_is_claimed_is_not_lost(client, db):
    me, agent, run_id, key = await _world(client, db)
    sock = _FakeSocket()
    conn = await _fake_conn(me, agent, sock)
    conn.capabilities.add("steer/1")
    try:
        s, run = await _claim(me, agent)
        async with s:
            cid = await _message(client, key, "Log retries")  # after the claim, before run_start
            assert await _send_start(s, conn, uuid.UUID(agent["id"]), run)
    finally:
        registry._conns.pop(me.id, None)
    start = next(m for m in map(json.loads, sock.sent) if m["type"] == "run_start")
    assert "> Log retries" in start["prompt"]
    assert (await _state(client, key, cid))["state"] == "given_at_start"


async def test_send_failure_releases_the_messages(client, db):
    me, agent, run_id, key = await _world(client, db)
    cid = await _message(client, key, "Log retries")
    assert await _dispatch(me, agent, _FakeSocket(fail=True)) is None
    assert (await _state(client, key, cid))["state"] == "waiting"


async def test_run_that_never_produced_anything_gives_them_back(client, db):
    me, agent, run_id, key = await _world(client, db)
    cid = await _message(client, key, "Log retries")
    await _dispatch(me, agent)
    async with SessionLocal() as s:
        await apply_update(s, me.id, run_id, 1, "model_options", {"options": []})  # before the prompt: not work
        await s.commit()
    async with SessionLocal() as s:
        await finish_run(s, me.id, run_id, "failed", "", "session_failed")
    assert (await _state(client, key, cid))["state"] == "waiting"


async def test_run_that_produced_output_keeps_them_delivered(client, db):
    me, agent, run_id, key = await _world(client, db)
    cid = await _message(client, key, "Log retries")
    await _dispatch(me, agent)
    async with SessionLocal() as s:
        await apply_update(s, me.id, run_id, 1, "message", {"text": "on it"})
        await s.commit()
    async with SessionLocal() as s:
        await finish_run(s, me.id, run_id, "failed", "", "prompt_failed")
    assert (await _state(client, key, cid))["state"] == "given_at_start"
