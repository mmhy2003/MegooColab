"""Runner protocol v2: capabilities, workflow run_start fields, run tokens and run metadata."""

import asyncio
import json
import time
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from starlette.websockets import WebSocketDisconnect

from app.agent_runs.models import AgentRun
from app.agent_runs.service import dispatch_pending
from app.core.db import SessionLocal
from app.core.security import hash_token
from app.projects.models import Project
from app.runner.protocol import RunFile, RunStart, RunTask
from app.runner.registry import BRANCH_PROBLEM, WORKFLOW_PROBLEM, RunnerConn, registry
from app.tasks.models import Task
from app.workflow.models import DocKind, DocStatus, WorkflowDocument
from tests.agent_runs.test_dispatch import (
    _avail,
    _fake_conn,
    _FakeSocket,
    _offline_runs,
    _setup,
    _start,
    _wait_run,
)
from tests.runner.test_runner_ws import (
    URL,
    _hello,
    _manager_with_project,
    _wait_status,
)

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
V2_KEYS = {"role", "stage", "step", "resume_session_id", "resume_prompt", "mcp", "files", "repo_files", "commit_message"}
SHA = "a" * 40


def _hello_v2(agent, capabilities=("workflow/1", "branch/1")):
    return _hello([_avail(agent)], capabilities=capabilities)


async def _make_workflow(db, run_id: str, role: str = "implement", **fields) -> None:
    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == uuid.UUID(run_id))
        .values(workflow_role=role, stage="build", step=2, **fields)
    )
    await db.commit()


def _mcp_status(tc, token: str) -> int:
    return tc.post("/api/mcp", json=TOOLS_LIST, headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"}).status_code


async def _row(db, run_id: str) -> AgentRun:
    return (
        await db.execute(
            select(AgentRun).where(AgentRun.id == uuid.UUID(run_id)).execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_v1_runner_hello_still_accepted(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task, prompt="Go")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)], capabilities=None))  # no capabilities field
        _wait_status(tc, agent["id"], "online")  # accepted, but it is sent no task run (no branch/1)
        assert (await _row(db, run["id"])).status == "queued"
        ws.send_json(_hello([_avail(agent)], capabilities=["branch/1"]))
        start = ws.receive_json()
        assert start["run_id"] == run["id"]
        assert V2_KEYS.isdisjoint(start)  # a plain run keeps the v1 shape, plus its branch
        assert start["branch"] == {"branch_from": "", "start_branch": "", "repositories": []}
        _wait_status(tc, agent["id"], "busy")


async def test_the_hello_records_the_runners_version(db, tc_factory):
    """The agents carry it, so the app can tell when a newer runner is out."""
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, _task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent))
        _wait_status(tc, agent["id"], "online")
        mine = tc.get("/api/agents/mine").json()
        assert [a["runner"] for a in mine if a["id"] == agent["id"]] == [{"version": "0.1.0", "os": "linux"}]


async def test_workflow_run_not_dispatched_without_capability_and_problem_shown(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    await _make_workflow(db, run["id"])
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)], capabilities=["branch/1"]))  # no workflow/1
        _wait_status(tc, agent["id"], "online")
        mine = next(a for a in tc.get("/api/agents/mine").json() if a["id"] == agent["id"])
        assert mine["problems"] == [WORKFLOW_PROBLEM]
        assert WORKFLOW_PROBLEM == "runner too old for workflows — update megoocolab-runner"
        assert (await _row(db, run["id"])).status == "queued"
        # the same runner, now with the capability, gets it exactly once
        ws.send_json(_hello_v2(agent))
        start = ws.receive_json()
        assert start["run_id"] == run["id"] and start["role"] == "implement"
    mine = next(a for a in tc.get("/api/agents/mine").json() if a["id"] == agent["id"])
    assert mine["problems"] == []


async def test_run_start_carries_mcp_token_valid_only_while_running(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    await _make_workflow(db, run["id"], resume_session_ref="sess-1", resume_prompt="Carry on")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent))
        start = ws.receive_json()
        raw = start["mcp"]["token"]
        assert start["mcp"]["url"] == "http://localhost:8080/api/mcp"
        assert raw.startswith("mgr_")
        assert (start["role"], start["stage"], start["step"]) == ("implement", "build", 2)
        assert (start["resume_session_id"], start["resume_prompt"]) == ("sess-1", "Carry on")
        assert start["prompt"]  # the full prompt stays as the runner's fallback
        # run_start is sent before the commit that stores the token's hash: wait for that commit
        deadline = time.monotonic() + 5
        while (row := await _row(db, run["id"])).mcp_token_hash is None:
            assert time.monotonic() < deadline, "the run token was never stored"
            await asyncio.sleep(0.02)
        assert row.mcp_token_hash == hash_token(raw) and raw not in (row.mcp_token_hash, row.prompt)
        assert _mcp_status(tc, raw) == 200
        assert _mcp_status(tc, "mgr_" + "x" * 43) == 401
        ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "completed", "summary": "ok"})
        _wait_run(tc, task, run["id"], "completed")
        assert _mcp_status(tc, raw) == 401
        assert (await _row(db, run["id"])).mcp_token_hash is None


async def test_run_finished_stores_session_and_git_state(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    await _make_workflow(db, run["id"])
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent))
        assert ws.receive_json()["run_id"] == run["id"]
        ws.send_json({
            "type": "run_finished", "run_id": run["id"], "outcome": "completed", "summary": "done",
            "session_id": "acp-session-9",
            "git_before": {"head": SHA, "branch": "megoo/PAY-1", "dirty": False},
            "git_after": {"head": "b" * 40, "branch": None, "dirty": True},
        })
        _wait_run(tc, task, run["id"], "completed")
    row = await _row(db, run["id"])
    assert row.session_ref == "acp-session-9"
    assert row.git_before == {"head": SHA, "branch": "megoo/PAY-1", "dirty": False}
    assert row.git_after == {"head": "b" * 40, "branch": None, "dirty": True}


async def test_run_finished_rejects_bad_git_state(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, _agent, _task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json({
            "type": "run_finished", "run_id": str(uuid.uuid4()), "outcome": "completed", "summary": "",
            "git_after": {"head": "nothex", "branch": None, "dirty": False},
        })
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                ws.receive_json()
        assert exc.value.code == 4400


def _start_kwargs(**over):
    return {
        "run_id": uuid.uuid4(), "agent_id": uuid.uuid4(), "local_path": "/r", "policy": "workspace",
        "prompt": "p", "task": RunTask(key="PAY-1", title="t", description_md="", project_key="PAY"), **over,
    }


@pytest.mark.parametrize(
    "path",
    ["design.md", "/etc/passwd", ".megoocolab/../x", "../.megoocolab/x", ".megoocolab\\x.md", "C:/x",
     ".megoocolab/", ".megoocolab//x", ".megoocolab/./x", "docs/superpowers/x.md", ".megoocolab/a\x00b",
     ".megoocolab/a:b.md", ".megoocolab/a.", ".megoocolab/a ", ".megoocolab/CON", ".megoocolab/nul.md",
     ".megoocolab/Com1.txt", ".megoocolab/lpt9.md", ".megoocolab/ x.md", ".megoocolab/a*b", ".megoocolab/\u00e9.md",
     ".megoocolab/a../b"],
)
def test_files_paths_validated(path):
    with pytest.raises(ValueError):
        RunStart(**_start_kwargs(files=[RunFile(path=path, content="x")]))


@pytest.mark.parametrize(
    "path",
    ["plan.md", "docs/superpowers/../x.md", "docs/superpowers\\x.md", "/docs/superpowers/x.md",
     ".megoocolab/x.md", "docs/superpowers/", "docs/superpowersx/y.md", "docs/superpowers/specs/aux.md",
     "docs/superpowers/plans/a:b.md", "docs/superpowers/plans/x."],
)
def test_repo_files_paths_validated(path):
    with pytest.raises(ValueError):
        RunStart(**_start_kwargs(repo_files=[RunFile(path=path, content="x")]))


def test_valid_paths_and_size_cap():
    ok = RunStart(
        **_start_kwargs(
            files=[RunFile(path=".megoocolab/design.md", content="d")],
            repo_files=[RunFile(path="docs/superpowers/specs/PAY-1-design.md", content="d")],
        )
    )
    assert ok.files[0].path == ".megoocolab/design.md"
    mb = "x" * (1024 * 1024)
    RunStart(**_start_kwargs(files=[RunFile(path=f".megoocolab/{i}.md", content=mb) for i in range(2)]))  # 2 MB
    with pytest.raises(ValidationError):  # UTF-8 bytes, not characters
        RunStart(**_start_kwargs(files=[RunFile(path=".megoocolab/a.md", content="é" * (1024 * 1024 + 1))]))
    with pytest.raises(ValueError):
        RunStart(
            **_start_kwargs(
                files=[RunFile(path=f".megoocolab/{i}.md", content=mb) for i in range(2)]
                + [RunFile(path=".megoocolab/z.md", content="y")]
            )
        )


async def _docs(db, task_key_number: int, rows: list[tuple[str, int, str, str]]) -> None:
    task_id = (await db.execute(select(Task.id).where(Task.number == task_key_number))).scalar_one()
    for kind, version, status, body in rows:
        db.add(WorkflowDocument(task_id=task_id, kind=DocKind(kind), version=version, status=DocStatus(status), body_md=body))
    await db.commit()


async def _dispatch_one(client, db, role: str, *, commit_docs: bool = False) -> dict:
    me, agent, runs = await _offline_runs(client, db)
    await _make_workflow(db, runs[0]["id"], role)
    await _docs(db, 1, [
        ("design", 1, "superseded", "OLD design"), ("design", 2, "approved", "APPROVED design"),
        ("design", 3, "submitted", "PENDING design"),
        ("plan", 1, "approved", "APPROVED plan"), ("plan", 2, "rejected", "REJECTED plan"),
    ])
    if commit_docs:
        await db.execute(update(Project).values(commit_docs_to_repo=True))
        await db.commit()
    sock = _FakeSocket()
    await _fake_conn(me, agent, sock)  # a current runner, its machine linked to the agent
    try:
        async with SessionLocal() as s:
            await dispatch_pending(s, me.id)
            await s.commit()
    finally:
        registry._conns.pop(me.id, None)
    return next(m for m in map(json.loads, sock.sent) if m["type"] == "run_start")


async def test_implement_run_carries_latest_approved_design_and_plan(client, db):
    start = await _dispatch_one(client, db, "implement", commit_docs=True)
    assert {f["path"]: f["content"] for f in start["files"]} == {
        ".megoocolab/design.md": "APPROVED design", ".megoocolab/plan.md": "APPROVED plan",
    }
    assert start["repo_files"] == [] and start["commit_message"] is None


async def test_brainstorm_run_carries_no_files(client, db):
    start = await _dispatch_one(client, db, "brainstorm")
    assert start["files"] == [] and start["mcp"]["token"].startswith("mgr_")


async def test_finish_run_repo_files_only_when_project_commits_docs(client, db):
    start = await _dispatch_one(client, db, "finish")
    assert start["repo_files"] == [] and len(start["files"]) == 2


async def test_finish_run_with_commit_docs_gets_repo_files(client, db):
    start = await _dispatch_one(client, db, "finish", commit_docs=True)
    assert {f["path"]: f["content"] for f in start["repo_files"]} == {
        "docs/superpowers/specs/PAY-1-design.md": "APPROVED design",
        "docs/superpowers/plans/PAY-1-plan.md": "APPROVED plan",
    }
    assert start["commit_message"] == "docs: PAY-1 design and plan"


async def test_failed_send_requeues_and_clears_token(client, db):
    me, agent, runs = await _offline_runs(client, db)
    await _make_workflow(db, runs[0]["id"])
    await _fake_conn(me, agent, _FakeSocket(fail=True))
    try:
        async with SessionLocal() as s:
            await dispatch_pending(s, me.id)
            await s.commit()
    finally:
        registry._conns.pop(me.id, None)
    row = await _row(db, runs[0]["id"])
    assert row.status == "queued" and row.mcp_token_hash is None


async def test_oversized_documents_fail_the_run_without_a_token(client, db):
    me, agent, runs = await _offline_runs(client, db)
    await _make_workflow(db, runs[0]["id"])
    await _docs(db, 1, [("design", 1, "approved", "é" * 600_000), ("plan", 1, "approved", "é" * 600_000)])
    sock = _FakeSocket()
    await _fake_conn(me, agent, sock)  # a current runner, its machine linked to the agent
    try:
        async with SessionLocal() as s:
            await dispatch_pending(s, me.id)
            await s.commit()
    finally:
        registry._conns.pop(me.id, None)
    row = await _row(db, runs[0]["id"])
    assert sock.sent == [] and row.status == "failed" and row.reason == "invalid_run_files"
    assert row.mcp_token_hash is None


async def test_token_cleared_when_runner_disconnects(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    await _make_workflow(db, run["id"])
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent))
        raw = ws.receive_json()["mcp"]["token"]
        # run_start is sent before the commit that stores the token's hash: wait for that commit
        deadline = time.monotonic() + 5
        while _mcp_status(tc, raw) != 200:
            assert time.monotonic() < deadline, "the run token never became valid"
            await asyncio.sleep(0.02)
    _wait_run(tc, task, run["id"], "failed")
    assert _mcp_status(tc, raw) == 401
    assert (await _row(db, run["id"])).mcp_token_hash is None


async def test_each_send_gets_a_fresh_token(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    await _make_workflow(db, run["id"])
    seen = []
    for _ in range(2):
        with tc.websocket_connect(URL, headers=token["headers"]) as ws:
            ws.receive_json()
            ws.send_json(_hello_v2(agent))
            start = ws.receive_json()
            seen.append(start["mcp"]["token"])
            if len(seen) == 1:
                ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "failed", "summary": ""})
                _wait_run(tc, task, run["id"], "failed")
                await db.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(run["id"])).values(
                    status="queued", started_at=None))
                await db.commit()
    assert seen[0] != seen[1] and _mcp_status(tc, seen[0]) == 401


async def test_run_token_never_authenticates_rest(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    await _make_workflow(db, run["id"])
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent))
        raw = ws.receive_json()["mcp"]["token"]
        anon = tc_factory()  # no session cookie
        h = {"Authorization": f"Bearer {raw}"}
        for method, path in (("get", "/api/projects"), ("get", f"/api/tasks/{task['key']}"),
                             ("get", "/api/auth/me"), ("get", "/api/tokens/self"),
                             ("post", f"/api/tasks/{task['key']}/workflow/start")):
            assert getattr(anon, method)(path, headers=h).status_code == 401, path
        # even with a logged-in cookie, a bearer header is refused on REST
        assert tc.get("/api/projects", headers=h).status_code == 401


async def test_token_cleared_when_run_is_cancelled(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    await _make_workflow(db, run["id"])
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent))
        raw = ws.receive_json()["mcp"]["token"]
        assert tc.post(f"/api/agent-runs/{run['id']}/cancel").status_code == 204
        assert ws.receive_json()["type"] == "run_cancel"
        ws.send_json({"type": "run_finished", "run_id": run["id"], "outcome": "cancelled", "summary": ""})
        _wait_run(tc, task, run["id"], "cancelled")
    assert _mcp_status(tc, raw) == 401
    assert (await _row(db, run["id"])).mcp_token_hash is None


async def test_nul_characters_in_run_finished_do_not_wedge_the_run(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    run = _start(tc, task)
    await _make_workflow(db, run["id"])
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(agent))
        assert ws.receive_json()["run_id"] == run["id"]
        ws.send_json({
            "type": "run_finished", "run_id": run["id"], "outcome": "completed", "summary": "o\u0000k",
            "session_id": "s\u0000id", "error": "e\u0000",
            "git_before": {"head": SHA, "branch": "a\u0000b", "dirty": False},
        })
        _wait_run(tc, task, run["id"], "completed")
    row = await _row(db, run["id"])
    assert row.mcp_token_hash is None and row.session_ref == "sid" and row.summary == "ok"
    assert row.git_before["branch"] == "ab"


def test_runner_reported_strings_are_bounded_and_nul_free():
    from app.runner.protocol import runner_message

    agent = str(uuid.uuid4())
    msg = runner_message.validate_python(
        {"type": "agent_status", "agent_id": agent, "available": False, "problems": ["a\u0000b"]}
    )
    assert msg.problems == ["ab"]
    long = runner_message.validate_python(
        {"type": "agent_status", "agent_id": agent, "available": False, "problems": ["x" * 250] + ["y"] * 11}
    )
    assert len(long.problems) == 10 and len(long.problems[0]) == 200  # truncated, never rejected
    assert runner_message.validate_python({"type": "run_update", "run_id": agent, "seq": 1, "kind": "m\u0000", "data": {}}).kind == "m"


async def test_runner_problems_visible_to_owner_and_admins_only(db):
    from app.agents.service import agent_problems
    from app.auth.models import Role
    from tests.factories import make_user

    owner, admin, other = await make_user(db), await make_user(db, role=Role.admin), await make_user(db)
    agent_id = uuid.uuid4()
    conn = RunnerConn(owner.id, owner.id, _FakeSocket())
    conn.owned_agents.add(agent_id)
    conn.set_availability(agent_id, False, ["claude not installed"])
    registry._conns[owner.id] = conn
    try:
        assert agent_problems(agent_id, owner.id, owner) == ["claude not installed", WORKFLOW_PROBLEM, BRANCH_PROBLEM]
        assert agent_problems(agent_id, owner.id, admin) == ["claude not installed", WORKFLOW_PROBLEM, BRANCH_PROBLEM]
        assert agent_problems(agent_id, owner.id, other) == [WORKFLOW_PROBLEM, BRANCH_PROBLEM]
        conn.capabilities = {"workflow/1", "branch/1"}
        assert agent_problems(agent_id, owner.id, other) == []
    finally:
        registry._conns.pop(owner.id, None)


def test_v2_start_fields_are_exactly_the_non_v1_fields():
    from app.runner.protocol import V2_START_FIELDS

    assert V2_START_FIELDS == {
        "role", "stage", "step", "resume_session_id", "resume_prompt", "mcp", "files", "repo_files", "commit_message",
    }


async def test_hello_with_too_many_or_too_long_problems_is_truncated_not_rejected(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, _task = _setup(tc)
    problems = ["C:\\" + "d" * 250 + " is not a git repository"] + [f"problem {i}" for i in range(10)]
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json({
            **_hello([{"agent_id": agent["id"], "available": False, "problems": problems}]),
            "runner_version": "v" * 300,
        })
        ws.send_json({"type": "heartbeat"})  # the socket is still up
        deadline = time.monotonic() + 3
        while True:
            mine = next(a for a in tc.get("/api/agents/mine").json() if a["id"] == agent["id"])
            if mine["problems"][:1] and len(mine["problems"]) > 1:
                break
            assert time.monotonic() < deadline
            await asyncio.sleep(0.02)
        shown = [p for p in mine["problems"] if p != WORKFLOW_PROBLEM]
        assert len(shown) == 10 and all(len(p) <= 200 for p in shown)


def test_files_size_cap_message_names_the_real_cap():
    with pytest.raises(ValidationError, match="files exceed 2 MB"):
        RunStart(**_start_kwargs(files=[RunFile(path=".megoocolab/a.md", content="x" * (2 * 1024 * 1024 + 1))]))
