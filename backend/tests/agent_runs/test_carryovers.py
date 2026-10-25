"""Plan 2 review carry-overs: NUL stripping, the cancel actor, and two delete/dispatch races."""

import asyncio
import time
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.agent_runs.models import AgentRun, RunStatus
from app.agent_runs.service import (
    _lock_run,
    _transition,
    stop_runs_before_delete,
)
from app.auth.models import Role, User
from app.core.db import SessionLocal
from app.tasks.activity import safe_filename
from app.tasks.models import Comment, Task, TaskEvent
from app.workflow import engine
from tests.agent_runs.test_dispatch import (
    _avail,
    _offline_runs,
    _run_status,
    _setup,
    _start,
    _task,
    _wait_run,
)
from tests.agent_runs.test_run_guards import _finish, _next_of
from tests.factories import login, make_project, make_user
from tests.mcp.test_mcp import _mint as _mint_mcp
from tests.mcp.test_mcp import call, mcp_running, mcp_session  # noqa: F401  (mcp_running is a fixture)
from tests.runner.test_runner_ws import (  # noqa: F401  (tc_factory is a fixture)
    URL,
    _hello,
    _manager_with_project,
    tc_factory,
)


async def test_task_title_and_description_strip_nul(app, client, db, mcp_running):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    r = await client.post("/api/projects/PAY/tasks", json={"title": "a\x00b", "description_md": "c\x00d"})
    assert r.status_code == 201, r.text
    assert (r.json()["title"], r.json()["description_md"]) == ("ab", "cd")

    r = await client.patch(f"/api/tasks/{r.json()['key']}", json={"title": "e\x00f", "description_md": "g\x00h"})
    assert r.status_code == 200, r.text
    assert (r.json()["title"], r.json()["description_md"]) == ("ef", "gh")

    async with mcp_session(app, await _mint_mcp(client)) as s:
        is_error, created = await call(s, "create_task", project_key="PAY", title="a\x00b", description_md="c\x00d")
        assert not is_error, created
        assert (created["title"], created["description_md"]) == ("ab", "cd")
        is_error, updated = await call(s, "update_task", key=created["key"], title="x\x00y", description_md="z\x00")
        assert not is_error, updated
        assert (updated["title"], updated["description_md"]) == ("xy", "z")
    titles = (await db.execute(select(Task.title).execution_options(populate_existing=True))).scalars().all()
    assert all("\x00" not in t for t in titles)


async def test_comment_body_strips_nul(app, client, db, mcp_running):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "T"})).json()
    r = await client.post(f"/api/tasks/{task['key']}/comments", json={"body_md": "a\x00b"})
    assert r.status_code == 201, r.text
    assert r.json()["body_md"] == "ab"
    async with mcp_session(app, await _mint_mcp(client)) as s:
        is_error, payload = await call(s, "comment_on_task", key=task["key"], body_md="c\x00d")
        assert not is_error, payload
    bodies = (await db.execute(select(Comment.body_md).order_by(Comment.created_at))).scalars().all()
    assert bodies == ["ab", "cd"]


async def test_user_cancel_records_actor(db, tc_factory):
    tc = tc_factory(lifespan=True)
    me, _ = await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert _next_of(ws, "run_start")["run_id"] == run["id"]
        _wait_run(tc, task, run["id"], "running")
        assert tc.post(f"/api/agent-runs/{run['id']}/cancel").status_code == 204
        assert _next_of(ws, "run_cancel")["run_id"] == run["id"]
        _finish(ws, run["id"], "cancelled")  # arrives later, after the cancel request returned
        _wait_run(tc, task, run["id"], "cancelled")
    event = (
        await db.execute(select(TaskEvent).where(TaskEvent.kind == "agent_run_cancelled"))
    ).scalar_one()
    assert event.actor_user_id == me.id
    row = (await db.execute(select(AgentRun).execution_options(populate_existing=True))).scalar_one()
    assert row.cancelled_by == me.id


async def _until_event(db, kind: str) -> None:
    deadline = time.monotonic() + 3
    while (await db.execute(select(TaskEvent.id).where(TaskEvent.kind == kind))).first() is None:
        assert time.monotonic() < deadline, f"no {kind} event"
        await db.rollback()
        await asyncio.sleep(0.02)


async def test_finish_of_deleted_run_dispatches_next_queued(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, t1 = _setup(tc)
    t2 = _task(tc, agent, title="Second")
    first = _start(tc, t1)
    second = _start(tc, t2)  # max_concurrent_runs is 1: waits behind the first
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert _next_of(ws, "run_start")["run_id"] == first["id"]
        _wait_run(tc, t1, first["id"], "running")
        # the socket handles messages in order: once this update is stored, the hello's dispatch has finished
        ws.send_json({"type": "run_update", "run_id": first["id"], "seq": 1, "kind": "message", "data": {"text": "x"}})
        await _until_event(db, "agent_message")
        assert tc.delete(f"/api/tasks/{t1['key']}").status_code == 204
        assert _next_of(ws, "run_cancel")["run_id"] == first["id"]
        # deleting dispatches nothing: the delete has returned, and the queued run was not claimed
        assert _run_status(tc, t2, second["id"]) == "queued"
        _finish(ws, first["id"], "cancelled")  # the row is gone, but the slot is free
        assert _next_of(ws, "run_start")["run_id"] == second["id"]
        _wait_run(tc, t2, second["id"], "running")


async def test_start_run_on_deleted_task_404(client, db):
    me, agent, _runs = await _offline_runs(client, db, n=0)
    agent_id = agent["id"]
    task_json = (
        await client.post("/api/projects/PAY/tasks", json={"title": "Gone", "assignee_agent_id": agent_id})
    ).json()
    task = (await db.execute(select(Task).where(Task.id == uuid.UUID(task_json["id"])))).scalar_one()
    user = await db.get(User, me.id)
    async with SessionLocal() as other:  # deleted by someone else after this request loaded the task
        await other.execute(delete(Task).where(Task.id == task.id))
        await other.commit()
    with pytest.raises(HTTPException) as exc:
        await engine.start(db, user, task)  # runs start only through the workflow engine
    assert exc.value.status_code == 404 and exc.value.detail == "task_not_found"


# ---- review round 1 ---------------------------------------------------------


async def test_nul_only_text_is_rejected_and_length_counts_stripped_text(app, client, db, mcp_running):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    r = await client.post("/api/projects/PAY/tasks", json={"title": "\x00"})
    assert r.status_code == 422
    r = await client.post("/api/projects/PAY/tasks", json={"title": "a" * 500 + "\x00"})
    assert r.status_code == 201 and r.json()["title"] == "a" * 500
    task = r.json()
    async with mcp_session(app, await _mint_mcp(client)) as s:
        is_error, payload = await call(s, "comment_on_task", key=task["key"], body_md="\x00")
    assert is_error and "invalid_input" in payload
    assert (await db.execute(select(Comment.id))).first() is None


async def test_other_text_inputs_strip_nul(client, db):
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    r = await client.post("/api/teams", json={"name": "T\x00eam", "description": "d\x00"})
    assert r.status_code == 201, r.text
    assert (r.json()["name"], r.json()["description"]) == ("Team", "d")
    r = await client.post("/api/agents", json={"program": "claude_code", "name": "A\x00gent"})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Agent"
    assert safe_filename("a\x00b.txt") == "ab.txt"


async def test_stop_runs_before_delete_does_not_deadlock_with_event_inserts(client, db):
    """The delete holds the task lock while a cancel (run lock, then a TaskEvent insert, whose FK check
    locks the task FOR KEY SHARE) finishes: FOR UPDATE on the task would deadlock here."""
    _me, _agent, [run_json] = await _offline_runs(client, db)
    run_id = uuid.UUID(run_json["id"])
    task_id = (await db.execute(select(AgentRun.task_id).where(AgentRun.id == run_id))).scalar_one()
    async with SessionLocal() as canceller, SessionLocal() as deleter:
        run = await _lock_run(canceller, run_id)  # the cancel already holds the run row
        delete_task = asyncio.create_task(stop_runs_before_delete(deleter, [task_id]))
        await asyncio.sleep(0.5)  # the delete now holds the task lock and waits for the run row
        assert not delete_task.done()
        await asyncio.wait_for(
            _transition(canceller, run, RunStatus.cancelled, "agent_run_cancelled", owner_id=_me.id), 5
        )
        await canceller.commit()
        await asyncio.wait_for(delete_task, 5)
        await deleter.rollback()
    assert (await db.execute(select(TaskEvent).where(TaskEvent.kind == "agent_run_cancelled"))).scalars().all()


async def test_disconnect_after_user_cancel_ends_cancelled_with_actor(db, tc_factory):
    tc = tc_factory(lifespan=True)
    me, _ = await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert _next_of(ws, "run_start")["run_id"] == run["id"]
        _wait_run(tc, task, run["id"], "running")
        assert tc.post(f"/api/agent-runs/{run['id']}/cancel").status_code == 204
        assert _next_of(ws, "run_cancel")["run_id"] == run["id"]
    _wait_run(tc, task, run["id"], "cancelled")  # the runner left before its run_finished
    event = (await db.execute(select(TaskEvent).where(TaskEvent.kind == "agent_run_cancelled"))).scalar_one()
    assert event.actor_user_id == me.id
    assert "agent_run_failed" not in [k for (k,) in (await db.execute(select(TaskEvent.kind))).all()]
