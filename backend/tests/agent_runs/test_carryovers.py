"""Plan 2 review carry-overs: NUL stripping, the cancel actor, and two delete/dispatch races."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.agent_runs.models import AgentRun, RunPolicy
from app.agent_runs.service import start_run
from app.auth.models import User
from app.core.db import SessionLocal
from app.projects.models import Project
from app.tasks.models import Comment, Task, TaskEvent
from tests.agent_runs.test_dispatch import (
    _avail,
    _offline_runs,
    _setup,
    _start,
    _task,
    _wait_run,
)
from tests.agent_runs.test_run_guards import _finish, _next_of
from tests.factories import login, make_project, make_user
from tests.mcp.test_mcp import call, mcp_running, mcp_session  # noqa: F401  (mcp_running is a fixture)
from tests.mcp.test_mcp import _mint as _mint_mcp
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
        assert tc.delete(f"/api/tasks/{t1['key']}").status_code == 204
        assert _next_of(ws, "run_cancel")["run_id"] == first["id"]
        _wait_run(tc, t2, second["id"], "queued")  # deleting dispatches nothing
        _finish(ws, first["id"], "cancelled")  # the row is gone, but the slot is free
        assert _next_of(ws, "run_start")["run_id"] == second["id"]
        _wait_run(tc, t2, second["id"], "running")


async def test_start_run_on_deleted_task_404(client, db):
    me, _agent, _runs = await _offline_runs(client, db, n=0)
    agent_id = _agent["id"]
    task_json = (
        await client.post("/api/projects/PAY/tasks", json={"title": "Gone", "assignee_agent_id": agent_id})
    ).json()
    task = (await db.execute(select(Task).where(Task.id == uuid.UUID(task_json["id"])))).scalar_one()
    project = await db.get(Project, task.project_id)
    user = await db.get(User, me.id)
    async with SessionLocal() as other:  # deleted by someone else after this request loaded the task
        await other.execute(delete(Task).where(Task.id == task.id))
        await other.commit()
    with pytest.raises(HTTPException) as exc:
        await start_run(db, user, task, project, RunPolicy.read_only, None)
    assert exc.value.status_code == 404 and exc.value.detail == "task_not_found"
