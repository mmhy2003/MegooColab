"""Branch from on the wire: run_start.branch, the runner's one-time branch report, the branch/1 capability."""

import asyncio
import time
import uuid

import pytest

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.runner.registry import BRANCH_PROBLEM, MODEL_PROBLEM, WORKFLOW_PROBLEM
from app.tasks.models import Task, TaskEvent
from tests.agent_runs.test_dispatch import _avail, _setup, _start, _wait_run
from tests.runner.test_runner_ws import URL, _hello, _manager_with_project, _wait_status

REPO = "https://github.com/acme/pay"


def _repo(tc, url=REPO, default="develop", name="pay"):
    r = tc.post("/api/projects/PAY/repositories",
                json={"name": name, "url": url, "provider": "github", "default_branch": default})
    assert r.status_code == 201, r.text


async def _task_row(task_id) -> Task:
    async with SessionLocal() as s:
        return await s.get(Task, uuid.UUID(task_id))


async def _events(task_id, kind) -> list[TaskEvent]:
    async with SessionLocal() as s:
        rows = await s.execute(select(TaskEvent).where(TaskEvent.task_id == uuid.UUID(task_id), TaskEvent.kind == kind))
        return list(rows.scalars())


async def _wait_for(check, what):
    deadline = time.monotonic() + 5
    while not await check():
        assert time.monotonic() < deadline, what
        await asyncio.sleep(0.02)


def _update(run_id, seq, data):
    return {"type": "run_update", "run_id": run_id, "seq": seq, "kind": "branch", "data": data}


async def test_run_start_carries_branch_for_plain_and_workflow_runs(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    _repo(tc)
    assert tc.patch(f"/api/tasks/{task['key']}", json={"branch_from": "main"}).status_code == 200
    run = _start(tc, task, prompt="Go")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        start = ws.receive_json()
        assert start["run_id"] == run["id"]
        assert start["branch"] == {
            "branch_from": "main", "start_branch": "",
            "repositories": [{"url": REPO, "default_branch": "develop"}],
        }
        ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "completed", "summary": "ok"})
        _wait_run(tc, task, run["id"], "completed")
    await db.execute(update(Task).where(Task.id == uuid.UUID(task["id"])).values(start_branch="main"))
    await db.commit()
    run2 = _start(tc, task, prompt="Again")
    await db.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(run2["id"])).values(
        workflow_role="implement", stage="build", step=1))
    await db.commit()
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        start = ws.receive_json()
        assert start["run_id"] == run2["id"] and start["role"] == "implement"
        assert start["branch"]["start_branch"] == "main"


async def _report(db, tc_factory, *reports):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task, prompt="Go")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        ws.receive_json()
        for seq, data in enumerate(reports, start=1):
            ws.send_json(_update(run["id"], seq, data))
        ws.send_json({"type": "run_update", "run_id": run["id"], "seq": len(reports) + 1, "kind": "message",
                      "data": {"text": "done"}})

        async def handled():
            return bool(await _events(task["id"], "agent_message"))

        await _wait_for(handled, "the updates were never handled")
    return task


async def test_branch_report_records_once(db, tc_factory):
    task = await _report(
        db, tc_factory,
        {"start_branch": "main", "default_branch": "develop", "repository_url": REPO},
        {"start_branch": "develop", "default_branch": "develop", "repository_url": REPO},
    )
    row = await _task_row(task["id"])
    assert (row.start_branch, row.back_merge_into) == ("main", "develop")
    [ev] = await _events(task["id"], "branch_started")
    assert ev.data == {"start_branch": "main", "back_merge_into": "develop"}
    assert await _events(task["id"], "agent_branch") == []


async def test_branch_report_same_as_default_has_no_back_merge(db, tc_factory):
    task = await _report(db, tc_factory, {"start_branch": "develop", "default_branch": "develop"})
    row = await _task_row(task["id"])
    assert (row.start_branch, row.back_merge_into) == ("develop", None)


async def test_branch_report_bad_names_ignored(db, tc_factory):
    task = await _report(db, tc_factory, {"start_branch": "a..b", "default_branch": "develop"})
    row = await _task_row(task["id"])
    assert row.start_branch is None
    assert await _events(task["id"], "branch_started") == []


async def test_runner_without_branch_capability_leaves_task_runs_queued(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task, prompt="Go")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)], capabilities=["workflow/1", "model/1"]))
        _wait_status(tc, agent["id"], "online")
        mine = next(a for a in tc.get("/api/agents/mine").json() if a["id"] == agent["id"])
        assert mine["problems"] == [BRANCH_PROBLEM]
        assert BRANCH_PROBLEM == "runner too old to choose the start branch — update megoocolab-runner"
        async with SessionLocal() as s:
            assert (await s.get(AgentRun, uuid.UUID(run["id"]))).status == "queued"
        ws.send_json(_hello([_avail(agent)], capabilities=["workflow/1", "branch/1", "model/1"]))
        assert ws.receive_json()["run_id"] == run["id"]
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:  # a v1 runner: both notices
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)], capabilities=None))
        _wait_status(tc, agent["id"], "online")
        mine = next(a for a in tc.get("/api/agents/mine").json() if a["id"] == agent["id"])
        assert mine["problems"] == [WORKFLOW_PROBLEM, BRANCH_PROBLEM, MODEL_PROBLEM]


@pytest.mark.parametrize("code", ["start_branch_missing", "repository_not_matched", "start_branch_fetch_failed"])
async def test_new_failure_codes_kept_as_reason(db, tc_factory, code):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task, prompt="Go")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        ws.receive_json()
        ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "failed", "summary": "",
                      "error": code})
        _wait_run(tc, task, run["id"], "failed")
    async with SessionLocal() as s:
        row = await s.get(AgentRun, uuid.UUID(run["id"]))
        assert row.reason == code
