"""Workflow MCP tools (Task 11): run-scoped `mgr_` tokens and connect-only personal `mgc_` tokens.

Run tokens are scoped to their run's task and role (Review Focus 3); personal tokens drive a connect_only,
unenforced workflow on the caller's own task, for which nothing is ever queued (AGT-32).
"""

import json
import secrets
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import func, select, update

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.core.security import hash_token
from app.mcp_server.auth import current_mcp_user_id, current_run
from app.projects.models import BoardColumn
from app.tasks.models import Comment, Task, TaskEvent
from app.workflow import engine, methodology
from app.workflow.models import (
    MethodologyVersion,
    Mockup,
    RunRole,
    StepReview,
    TaskWorkflow,
    WorkflowDocument,
    WorkflowQuestion,
)
from tests.agent_runs.test_dispatch import _task
from tests.runner.test_protocol_v2 import MCP_HEADERS
from tests.runner.test_runner_ws import _login
from tests.workflow.test_documents import STEPS, _design_waiting
from tests.workflow.test_engine import (
    _admin_client,
    _events,
    _finish,
    _member,
    _started,
    _wf,
)

ASKED = "Question posted. End your turn now; the answer arrives as your next message."
ALL_WORKFLOW_TOOLS = {
    "ask_human": {"question": "Which DB?"},
    "submit_design": {"markdown": "# Design"},
    "submit_plan": {"markdown": "# Plan", "steps": STEPS},
    "complete_step": {"step": 1, "summary": "Done", "tests_passed": True},
    "submit_review": {"verdict": "approved", "findings": []},
    "report_finish": {"outcome": "pr_opened", "branch": "megoo/PAY-1", "pr_url": "https://x.test/pr/1",
                      "tests_passed": True},
}
ALLOWED = {
    "ask_human": {"brainstorm", "plan", "implement", "step_fix", "final_fix", "finish"},
    "submit_design": {"brainstorm"},
    "submit_plan": {"plan"},
    "complete_step": {"implement", "step_fix"},
    "submit_review": {"step_review", "final_review"},
    "report_finish": {"finish"},
}


def _tool(tc, token: str, name: str, **args):
    """(is_error, payload): MCP JSON-RPC tools/call over the ASGI app. A 401 is (True, its detail)."""
    r = tc.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}},
        headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
    )
    if r.status_code == 401:
        return True, r.json()["detail"]
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    text = result["content"][0]["text"] if result["content"] else ""
    if result.get("isError"):
        return True, text
    structured = result.get("structuredContent")
    return False, (structured.get("result", structured) if structured else json.loads(text))


async def _run_token(run, **fields) -> str:
    """What the runner's run_start hands the agent: the run is running, with a fresh token."""
    raw = "mgr_" + secrets.token_urlsafe(32)
    async with SessionLocal() as s:
        await s.execute(
            update(AgentRun)
            .where(AgentRun.id == run.id)
            .values(status="running", started_at=datetime.now(UTC), mcp_token_hash=hash_token(raw), **fields)
        )
        await s.commit()
    return raw


async def _set_role(run, role: str, step: int | None = None) -> None:
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run.id).values(workflow_role=role, step=step))
        await s.commit()


def _personal(tc) -> str:
    r = tc.post("/api/tokens", json={"name": "my agent", "scopes": ["mcp"]})
    assert r.status_code == 201, r.text
    return r.json()["secret"]


def _my_task(tc, user, title="Mine") -> dict:
    r = tc.post("/api/projects/PAY/tasks", json={"title": title, "assignee_user_id": str(user.id)})
    assert r.status_code == 201, r.text
    return r.json()


async def _count(model, *where) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(model).where(*where))


async def _docs(task_id) -> list[WorkflowDocument]:
    async with SessionLocal() as s:
        rows = await s.execute(
            select(WorkflowDocument).where(WorkflowDocument.task_id == task_id).order_by(WorkflowDocument.version)
        )
        return list(rows.scalars())


async def _category(task_id) -> str:
    async with SessionLocal() as s:
        task = await s.get(Task, task_id)
        return (await s.get(BoardColumn, task.column_id)).category


# ---- run tokens (AGT-33, Review Focus 3) ----------------------------------------------------------


async def test_run_token_ask_human_creates_question_and_mockup(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    err, out = _tool(
        tc, token, "ask_human", key=b.key, question="Which layout?\x00",
        choices=[{"id": "grid", "label": "Grid", "recommended": True}, {"id": "list", "label": "List"}],
        mockup_html="<html><body><div data-megoo-choice='a'>A</div></body></html>", mockup_title="Layouts",
        mockup_choices=["a", "b"],
    )
    assert not err, out
    assert out == ASKED
    async with SessionLocal() as s:
        q = (await s.execute(select(WorkflowQuestion).where(WorkflowQuestion.task_id == b.task_id))).scalar_one()
        mockup = await s.get(Mockup, q.mockup_id)
    assert (q.run_id, q.stage, q.body, q.status) == (run.id, "brainstorm", "Which layout?", "open")
    assert [c["id"] for c in q.choices] == ["grid", "list"]
    assert (mockup.title, mockup.choices, mockup.version) == ("Layouts", ["a", "b"], 1)
    # the engine waits on the question once the asking run ends
    await _finish(b.manager.id, run, "completed")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "question")


async def test_run_token_wrong_task_refused(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    other = _task(tc, b.agent, title="Other")
    token = await _run_token(run)
    calls = {
        **ALL_WORKFLOW_TOOLS,
        "get_workflow": {},
        "get_document": {"kind": "design"},
        "get_task": {},
        "comment_on_task": {"body_md": "hi"},
    }
    # another task, an unknown project, garbage, a zero-padded number and a task id are all another key
    own_padded = b.key.replace("-", "-0")
    for name, args in calls.items():
        for key in (other["key"], "NOPE-1", "garbage", own_padded, b.task["id"], other["id"]):
            err, text = _tool(tc, token, name, key=key, **args)
            assert err and "wrong_task" in text, (name, key, text)
    other_id = uuid.UUID(other["id"])
    assert await _count(WorkflowQuestion) == 0 and await _count(WorkflowDocument) == 0
    assert await _count(Comment, Comment.task_id == other_id) == 0
    assert await _wf(other_id) is None
    # its own task is fine
    err, task = _tool(tc, token, "get_task", key=b.key)
    assert not err and task["key"] == b.key
    err, out = _tool(tc, token, "comment_on_task", key=b.key, body_md="Working on it")
    assert not err and out["comment_id"]
    # keys are case-insensitive, as over REST: its own key lowercased is still its own task
    err, task = _tool(tc, token, "get_task", key=b.key.lower())
    assert not err and task["key"] == b.key
    err, out = _tool(tc, token, "get_workflow", key=b.key.lower())
    assert not err and out["stage"] == "brainstorm"


async def test_tool_outside_role_refused(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _set_role(run, "implement", step=1)
    token = await _run_token(run)
    err, text = _tool(tc, token, "submit_plan", key=b.key, markdown="# Plan", steps=STEPS)
    assert err and "not_allowed_in_role" in text
    # every role against every tool it may not use; nothing changes
    before = await _wf(b.task_id)
    for role in RunRole:
        await _set_role(run, role.value, step=1)
        for name, args in ALL_WORKFLOW_TOOLS.items():
            if role.value in ALLOWED[name]:
                continue
            err, text = _tool(tc, token, name, key=b.key, **args)
            assert err and "not_allowed_in_role" in text, (role, name, text)
        # reads are open to every role
        err, out = _tool(tc, token, "get_workflow", key=b.key)
        assert not err and out["stage"] == "brainstorm", (role, out)
    after = await _wf(b.task_id)
    assert (after.stage, after.status, after.needs) == (before.stage, before.status, before.needs)
    assert await _count(WorkflowQuestion) == 0 and await _count(WorkflowDocument) == 0
    assert await _count(StepReview) == 0


async def test_run_token_stage_tools_reach_their_services(db, tc_factory):
    """Each stage tool passes the live run row to its service, so what the service records is kept."""
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    err, out = _tool(tc, token, "submit_design", key=b.key, markdown="# Design")
    assert not err and out == {"kind": "design", "version": 1, "status": "submitted"}

    await _set_role(run, "implement", step=2)
    err, text = _tool(tc, token, "complete_step", key=b.key, step=1, summary="x", tests_passed=True)
    assert err and "wrong_step" in text
    err, out = _tool(
        tc, token, "complete_step", key=b.key, step=2, summary="Added it", tests_passed=True, test_command="pytest"
    )
    assert not err, out
    async with SessionLocal() as s:
        row = await s.get(AgentRun, run.id)
        assert row.step_result == {"summary": "Added it", "tests_passed": True, "test_command": "pytest"}

    await _set_role(run, "step_review", step=2)
    finding = {"severity": "minor", "file": "a.py", "line": 3, "summary": "Naming"}
    err, out = _tool(tc, token, "submit_review", key=b.key, verdict="changes_requested", findings=[finding])
    assert not err, out
    async with SessionLocal() as s:
        review = (await s.execute(select(StepReview))).scalar_one()
        assert (review.run_id, review.verdict, review.step) == (run.id, "changes_requested", 2)

    await _set_role(run, "finish")
    err, out = _tool(tc, token, "report_finish", key=b.key, outcome="pr_opened", branch="megoo/PAY-1",
                     pr_url="https://git.test/pr/7", tests_passed=True)
    assert not err, out
    wf = await _wf(b.task_id)
    assert (wf.branch, wf.pr_url, wf.finish_outcome) == ("megoo/PAY-1", "https://git.test/pr/7", "pr_opened")


async def test_run_token_rejected_after_run_finished(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    assert not _tool(tc, token, "get_workflow", key=b.key)[0]
    await _finish(b.manager.id, run, "completed")
    for name, args in (("get_workflow", {}), ("submit_design", {"markdown": "# Late"}), ("whoami", {})):
        err, text = _tool(tc, token, name, **({"key": b.key} if name != "whoami" else {}), **args)
        assert err and text == "invalid_token", (name, text)
    assert await _count(WorkflowDocument) == 0


async def test_run_that_ends_mid_call_is_refused_under_the_lock(app, db, tc_factory):
    """The token resolved while the run was running; by the time the tool holds the workflow lock it has ended."""
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _run_token(run)
    async with SessionLocal() as s:
        resolved = await s.get(AgentRun, run.id)
        s.expunge(resolved)
    await _finish(b.manager.id, run, "completed")  # ends (and the engine nudges with a new run)
    wf_before = await _wf(b.task_id)
    user_reset, run_reset = current_mcp_user_id.set(b.manager.id), current_run.set(resolved)
    try:
        for name, args in (
            ("submit_design", {"markdown": "# Late"}),
            ("ask_human", {"question": "Late?"}),
            ("comment_on_task", {"body_md": "Late"}),
        ):
            with pytest.raises(ToolError, match="run_not_running"):
                await app.state.mcp.call_tool(name, {"key": b.key, **args})
    finally:
        current_run.reset(run_reset)
        current_mcp_user_id.reset(user_reset)
    assert await _count(WorkflowDocument) == 0 and await _count(WorkflowQuestion) == 0
    assert await _count(Comment) == 0
    wf = await _wf(b.task_id)
    assert (wf.stage, wf.status, wf.needs) == (wf_before.stage, wf_before.status, wf_before.needs)


async def test_list_tasks_refused_for_run_token(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    for name, args in (
        ("list_tasks", {"project_key": "PAY"}),
        ("list_projects", {}),
        ("create_task", {"project_key": "PAY", "title": "Sneaky"}),
        ("update_task", {"key": b.key, "title": "Renamed"}),
        ("move_task", {"key": b.key, "column": "Done"}),
    ):
        err, text = _tool(tc, token, name, **args)
        assert err and "not_allowed_in_role" in text, (name, text)
    assert await _count(Task) == 1
    assert tc.get(f"/api/tasks/{b.key}").json()["title"] == b.task["title"]
    err, me = _tool(tc, token, "whoami")
    assert not err and me["id"] == str(b.manager.id)


# ---- connect-only personal tokens (AGT-32) ------------------------------------------------------------


def _approve(tc, key: str, kind: str, version: int) -> None:
    r = tc.post(f"/api/tasks/{key}/documents/{kind}/{version}/decision", json={"approve": True})
    assert r.status_code == 200, r.text


async def _connect_only_building(tc, user) -> tuple[str, str]:
    """The user's own task, driven through their personal token to Build step 1: (key, token)."""
    key = _my_task(tc, user)["key"]
    token = _personal(tc)
    assert not _tool(tc, token, "submit_design", key=key, markdown="# Design")[0]
    _approve(tc, key, "design", 1)
    assert not _tool(tc, token, "submit_plan", key=key, markdown="# Plan", steps=STEPS)[0]
    _approve(tc, key, "plan", 1)
    return key, token


async def test_connect_only_flow_marks_unenforced_and_never_enqueues(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    runs_before = await _count(AgentRun)
    mine = _my_task(tc, b.manager)
    key, task_id = mine["key"], uuid.UUID(mine["id"])
    token = _personal(tc)

    err, out = _tool(tc, token, "get_workflow", key=key)
    assert not err and (out["stage"], out["status"]) == ("brainstorm", "idle")
    assert "ask_human" in out["next"] and "submit_design" in out["next"]
    assert await _wf(task_id) is None  # reading starts nothing
    err, text = _tool(tc, token, "submit_plan", key=key, markdown="# Plan", steps=STEPS)
    assert err and "wrong_stage" in text
    assert await _wf(task_id) is None
    for name in ("submit_review", "report_finish"):  # only runner-driven runs review and finish
        err, text = _tool(tc, token, name, key=key, **ALL_WORKFLOW_TOOLS[name])
        assert err and "not_allowed_in_role" in text, name

    # the first stage tool starts the workflow: connect_only, unenforced
    err, out = _tool(tc, token, "ask_human", key=key, question="Postgres or SQLite?")
    assert not err and out == ASKED
    wf = await _wf(task_id)
    assert (wf.driver, wf.enforcement, wf.stage) == ("connect_only", "unenforced", "brainstorm")
    assert (wf.status, wf.needs) == ("waiting_human", "question")
    async with SessionLocal() as s:
        q = (await s.execute(select(WorkflowQuestion).where(WorkflowQuestion.task_id == task_id))).scalar_one()
    assert q.run_id is None
    r = tc.post(f"/api/tasks/{key}/questions/{q.id}/answer", json={"text": "Postgres"})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["needs"]) == ("running", None)

    err, out = _tool(tc, token, "submit_design", key=key, markdown="# Design")
    assert not err and out["version"] == 1
    wf = await _wf(task_id)
    assert (wf.stage, wf.status, wf.needs) == ("design", "waiting_human", "design_approval")
    # a rejection hands the design back without a run; the revision waits again
    r = tc.post(f"/api/tasks/{key}/documents/design/1/decision", json={"approve": False, "comment": "More detail"})
    assert r.status_code == 200 and (r.json()["stage"], r.json()["status"]) == ("design", "running")
    assert not _tool(tc, token, "submit_design", key=key, markdown="# Design v2")[0]
    r = tc.post(f"/api/tasks/{key}/documents/design/2/decision", json={"approve": True})
    assert r.status_code == 200, r.text
    assert (r.json()["stage"], r.json()["status"], r.json()["needs"]) == ("plan", "running", None)

    err, text = _tool(tc, token, "submit_design", key=key, markdown="# Late design")
    assert err and "wrong_stage" in text
    assert not _tool(tc, token, "submit_plan", key=key, markdown="# Plan", steps=STEPS)[0]
    r = tc.post(f"/api/tasks/{key}/documents/plan/1/decision", json={"approve": True})
    assert r.status_code == 200, r.text
    assert (r.json()["stage"], r.json()["current_step"], r.json()["status"]) == ("build", 1, "running")
    async with SessionLocal() as s:
        subtasks = list((await s.execute(select(Task).where(Task.parent_id == task_id).order_by(Task.number))).scalars())
    assert len(subtasks) == 3

    err, text = _tool(tc, token, "complete_step", key=key, step=2, summary="skip ahead", tests_passed=True)
    assert err and "wrong_step" in text
    err, _ = _tool(tc, token, "complete_step", key=key, step=1, summary="tests red", tests_passed=False)
    assert not err and (await _wf(task_id)).current_step == 1  # failing tests keep the step
    for n in (1, 2):
        assert not _tool(tc, token, "complete_step", key=key, step=n, summary=f"Step {n}", tests_passed=True)[0]
        assert (await _wf(task_id)).current_step == n + 1
        assert await _category(subtasks[n - 1].id) == "done"
    assert not _tool(tc, token, "complete_step", key=key, step=3, summary="Step\x00 3", tests_passed=True,
                     test_command="uv run pytest")[0]
    async with SessionLocal() as s:
        events = (await s.execute(
            select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.kind == "step.completed")
            .order_by(TaskEvent.created_at, TaskEvent.id)
        )).scalars().all()
    assert events[-1].data == {"step": 3, "summary": "Step 3", "tests_passed": True, "test_command": "uv run pytest"}
    assert [e.data["summary"] for e in events] == ["tests red", "Step 1", "Step 2", "Step 3"]
    wf = await _wf(task_id)
    assert (wf.stage, wf.status, wf.needs, wf.enforcement) == ("done", "finished", None, "unenforced")
    assert await _category(task_id) == "done"
    err, text = _tool(tc, token, "ask_human", key=key, question="Anything else?")
    assert err and "workflow_finished" in text

    # finished, the task can change hands again
    member = await _member(db, tc)
    assert tc.patch(f"/api/tasks/{key}", json={"assignee_user_id": str(member.id)}).status_code == 200
    assert await _count(AgentRun) == runs_before  # nothing was ever queued for it
    with pytest.raises(HTTPException) as e:  # and the engine would refuse to
        async with SessionLocal() as s:
            wf = await s.get(TaskWorkflow, task_id)
            await engine.enqueue(s, wf, await s.get(Task, task_id), RunRole.implement, requested_by=b.manager.id)
    assert e.value.detail == "workflow_not_runner_driven"


async def test_hand_to_agent_queues_a_run_only_for_a_runner_driven_workflow(db, tc_factory):
    """The one path every human decision uses to give work back: a run, or (connect_only) just running again."""
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    mine = _my_task(tc, b.manager)
    token = _personal(tc)
    assert not _tool(tc, token, "ask_human", key=mine["key"], question="?")[0]
    async with SessionLocal() as s:
        task = await s.get(Task, uuid.UUID(mine["id"]))
        wf = await engine.lock_task(s, task)
        assert await engine.hand_to_agent(s, wf, task, RunRole.brainstorm, requested_by=b.manager.id) is None
        assert (wf.status, wf.needs) == ("running", None)
        await s.commit()
    assert await _count(AgentRun, AgentRun.task_id == uuid.UUID(mine["id"])) == 0
    async with SessionLocal() as s:
        task = await s.get(Task, b.task_id)
        wf = await engine.lock_task(s, task)
        await s.execute(update(AgentRun).where(AgentRun.task_id == b.task_id).values(status="cancelled"))
        queued = await engine.hand_to_agent(s, wf, task, RunRole.brainstorm, requested_by=b.manager.id)
        assert queued is not None and queued.workflow_role == "brainstorm" and queued.status == "queued"
        await s.rollback()


async def test_personal_token_refused_on_runner_driven_or_others_task(db, tc_factory):
    tc, other_tc = tc_factory(lifespan=True), tc_factory()
    b, _ = await _started(db, tc)
    token = _personal(tc)
    # the agent's task is driven by MegooColab: the human's own client cannot submit for their agent
    for name, args in {**ALL_WORKFLOW_TOOLS, "get_workflow": {}}.items():
        if name in ("submit_review", "report_finish"):
            continue
        err, text = _tool(tc, token, name, key=b.key, **args)
        assert err and "runner_driven" in text, (name, text)
    # someone else's task, or nobody's
    member = await _member(db, tc)
    theirs = _my_task(tc, member, title="Theirs")
    unassigned = tc.post("/api/projects/PAY/tasks", json={"title": "Nobody's"}).json()
    for task in (theirs, unassigned):
        for name in ("ask_human", "submit_design", "get_workflow"):
            err, text = _tool(tc, token, name, key=task["key"], **{**ALL_WORKFLOW_TOOLS, "get_workflow": {}}[name])
            assert err and "not_your_task" in text, (task["key"], name, text)
        assert await _wf(uuid.UUID(task["id"])) is None
    assert await _count(WorkflowQuestion) == 0 and await _count(WorkflowDocument) == 0
    # the member's own token works on their task
    _login(other_tc, member)
    err, out = _tool(other_tc, _personal(other_tc), "submit_design", key=theirs["key"], markdown="# Mine")
    assert not err, out


# ---- get_workflow / get_document ---------------------------------------------------------------------


async def test_get_workflow_returns_stage_instructions(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    err, out = _tool(tc, token, "get_workflow", key=b.key)
    assert not err, out
    assert (out["stage"], out["status"], out["needs"], out["current_step"], out["steps_total"]) == (
        "brainstorm", "running", None, None, None,
    )
    assert out["documents"] == []
    assert out["instructions"] == (await methodology.current(db, "brainstorm")).body_md
    assert out["next"] == "Ask questions with ask_human, then submit_design."
    # an implement run gets its role's hint
    await _set_role(run, "implement", step=1)
    err, out = _tool(tc, token, "get_workflow", key=b.key)
    assert "complete_step" in out["next"] and "step=1" in out["next"]

    # a personal token in Build: every Build key, each under its heading
    key, personal = await _connect_only_building(tc, b.manager)
    err, out = _tool(tc, personal, "get_workflow", key=key)
    assert not err, out
    assert (out["stage"], out["status"], out["current_step"], out["steps_total"]) == ("build", "running", 1, 3)
    assert out["documents"] == [{"kind": "design", "version": 1}, {"kind": "plan", "version": 1}]
    for k in ("build_implement", "build_step_review", "build_step_fix"):
        body = (await methodology.current(db, k)).body_md.strip()
        assert f"## {k}\n\n{body}" in out["instructions"], k
    assert "complete_step" in out["next"] and "step=1" in out["next"]

    err, doc = _tool(tc, personal, "get_document", key=key, kind="plan")
    assert not err and (doc["kind"], doc["version"], doc["status"], doc["body_md"]) == ("plan", 1, "approved", "# Plan")
    assert [s["title"] for s in doc["steps"]] == [s["title"] for s in STEPS]
    err, doc = _tool(tc, personal, "get_document", key=key, kind="design", version=1)
    assert not err and doc["body_md"] == "# Design" and doc["steps"] is None
    err, text = _tool(tc, personal, "get_document", key=key, kind="design", version=9)
    assert err and "document_not_found" in text
    err, text = _tool(tc, personal, "get_document", key=key, kind="nope")
    assert err and "invalid_kind" in text


async def test_oversized_and_nul_payloads_capped_or_rejected(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    err, text = _tool(tc, token, "submit_design", key=b.key, markdown="x" * 200_001)
    assert err and "too_large" in text
    err, text = _tool(tc, token, "ask_human", key=b.key, question="q" * 4_001)
    assert err and "too_large" in text
    err, text = _tool(tc, token, "ask_human", key=b.key, question="Look", mockup_html="<p>" + "x" * (2 * 1024 * 1024),
                      mockup_title="Big")
    assert err and "too_large" in text
    assert await _count(WorkflowDocument) == 0 and await _count(WorkflowQuestion) == 0 and await _count(Mockup) == 0

    err, out = _tool(tc, token, "submit_design", key=b.key, markdown="# De\x00sign\x00")
    assert not err, out
    err, out = _tool(tc, token, "ask_human", key=b.key, question="Wh\x00y?", mockup_html="<b>\x00hi</b>",
                     mockup_title="T\x00", mockup_choices=["a\x00"])
    assert not err, out
    [doc] = await _docs(b.task_id)
    assert doc.body_md == "# Design"
    async with SessionLocal() as s:
        q = (await s.execute(select(WorkflowQuestion))).scalar_one()
        mockup = await s.get(Mockup, q.mockup_id)
    assert (q.body, mockup.html, mockup.title, mockup.choices) == ("Why?", "<b>hi</b>", "T", ["a"])

    # the same caps for a connect-only caller
    mine = _my_task(tc, b.manager)
    personal = _personal(tc)
    err, text = _tool(tc, personal, "submit_design", key=mine["key"], markdown="y" * 200_001)
    assert err and "too_large" in text
    assert await _wf(uuid.UUID(mine["id"])) is None  # the refused call started nothing


# ---- round 1: reassignment, column guard, stage preconditions, methodology version --------------------


async def _questions(task_id) -> list[WorkflowQuestion]:
    async with SessionLocal() as s:
        rows = await s.execute(
            select(WorkflowQuestion).where(WorkflowQuestion.task_id == task_id).order_by(WorkflowQuestion.created_at)
        )
        return list(rows.scalars())


def _answer_open(tc, key: str, questions: list[WorkflowQuestion], text: str) -> None:
    [q] = [q for q in questions if q.status == "open"]
    r = tc.post(f"/api/tasks/{key}/questions/{q.id}/answer", json={"text": text})
    assert r.status_code == 200, r.text


async def test_active_connect_only_workflow_refuses_reassignment_and_column_drags(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    member = await _member(db, tc)
    mine = _my_task(tc, b.manager)
    key, task_id = mine["key"], uuid.UUID(mine["id"])
    token = _personal(tc)
    assert not _tool(tc, token, "ask_human", key=key, question="?")[0]  # waiting_human: active
    for body in ({"assignee_agent_id": b.agent["id"]}, {"assignee_user_id": str(member.id)}):
        r = tc.patch(f"/api/tasks/{key}", json=body)
        assert r.status_code == 409 and r.json()["detail"] == "workflow_active", (body, r.text)
    _answer_open(tc, key, await _questions(task_id), "ok")
    assert (await _wf(task_id)).status == "running"  # running: active too
    for body in ({"assignee_agent_id": b.agent["id"]}, {"assignee_user_id": str(member.id)}):
        r = tc.patch(f"/api/tasks/{key}", json=body)
        assert r.status_code == 409 and r.json()["detail"] == "workflow_active", (body, r.text)
    # the workflow moves its own card: no drag into review or done, by hand or over MCP
    for category in ("review", "done"):
        r = tc.post(f"/api/tasks/{key}/move", json={"column_id": b.cols[category]["id"]})
        assert r.status_code == 409 and r.json()["detail"] == "workflow_controls_column", category
        err, text = _tool(tc, token, "move_task", key=key, column=b.cols[category]["name"])
        assert err and "workflow_controls_column" in text, category
    task = tc.get(f"/api/tasks/{key}").json()
    assert (task["assignee_user_id"], task["assignee_agent_id"]) == (str(b.manager.id), None)
    assert task["column_id"] == mine["column_id"]
    assert (await _wf(task_id)).driver == "connect_only"
    # moving into a working column stays free
    r = tc.post(f"/api/tasks/{key}/move", json={"column_id": b.cols["working"]["id"]})
    assert r.status_code == 200, r.text


async def test_connect_only_stage_tools_need_a_running_workflow_without_open_question(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    mine = _my_task(tc, b.manager)
    key, task_id = mine["key"], uuid.UUID(mine["id"])
    token = _personal(tc)
    assert not _tool(tc, token, "ask_human", key=key, question="Which DB?")[0]
    err, text = _tool(tc, token, "submit_design", key=key, markdown="# D")
    assert err and "question_open" in text
    _answer_open(tc, key, await _questions(task_id), "Postgres")
    assert not _tool(tc, token, "submit_design", key=key, markdown="# D")[0]
    # waiting for the approval: not running, so no resubmission until a human decides
    err, text = _tool(tc, token, "submit_design", key=key, markdown="# D2")
    assert err and "workflow_not_running" in text
    # a question asked while the approval is pending stays open, and blocks the next submission
    assert not _tool(tc, token, "ask_human", key=key, question="Also?")[0]
    assert (await _wf(task_id)).needs == "design_approval"
    _approve(tc, key, "design", 1)
    err, text = _tool(tc, token, "submit_plan", key=key, markdown="# P", steps=STEPS)
    assert err and "question_open" in text
    _answer_open(tc, key, await _questions(task_id), "Yes")
    assert not _tool(tc, token, "submit_plan", key=key, markdown="# P", steps=STEPS)[0]
    _approve(tc, key, "plan", 1)
    assert not _tool(tc, token, "ask_human", key=key, question="Blocked?")[0]
    err, text = _tool(tc, token, "complete_step", key=key, step=1, summary="s", tests_passed=True)
    assert err and "question_open" in text
    wf = await _wf(task_id)
    assert (wf.stage, wf.current_step, wf.status, wf.needs) == ("build", 1, "waiting_human", "question")
    assert [(d.kind, d.version) for d in await _docs(task_id)] == [("design", 1), ("plan", 1)]


async def test_get_workflow_gives_the_runs_recorded_methodology_version(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_waiting(db, tc)
    r = tc.post(f"/api/tasks/{b.key}/documents/design/1/decision", json={"approve": False, "comment": "Simpler"})
    assert r.status_code == 200, r.text
    async with SessionLocal() as s:
        revision = (await s.execute(
            select(AgentRun).where(AgentRun.task_id == b.task_id).order_by(AgentRun.created_at.desc()).limit(1)
        )).scalar_one()
    assert (revision.workflow_role, revision.stage) == ("brainstorm", "design")
    token = await _run_token(revision)
    meth = await methodology.current(db, "design_revision")
    assert revision.methodology_version_id == meth.id
    # an admin edits the text mid-run: the run keeps the version it started with
    async with SessionLocal() as s:
        s.add(MethodologyVersion(key="design_revision", version=meth.version + 1, body_md="Edited text"))
        await s.commit()
    err, out = _tool(tc, token, "get_workflow", key=b.key)
    assert not err, out
    assert out["instructions"] == meth.body_md != "Edited text"
    assert (out["stage"], out["role"]) == ("design", "brainstorm")


# ---- an abandoned connect-only workflow (I2) ------------------------------------------------------


async def _members_connect_only(db, tc, tc_factory):
    """A plain member drives their own task through their personal token: (member client, key, task_id, token).
    The design is submitted, so the workflow waits for its approval."""
    member = await _member(db, tc)
    mc = tc_factory()
    _login(mc, member)
    mine = _my_task(tc, member)
    key, task_id = mine["key"], uuid.UUID(mine["id"])
    token = _personal(mc)
    assert not _tool(mc, token, "submit_design", key=key, markdown="# Design")[0]
    assert ((await _wf(task_id)).status, (await _wf(task_id)).needs) == ("waiting_human", "design_approval")
    return mc, key, task_id, token


async def test_admin_pauses_an_abandoned_connect_only_workflow_then_reassigns_it_to_an_agent(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    _, key, task_id, _ = await _members_connect_only(db, tc, tc_factory)
    other = tc_factory()
    _login(other, await _member(db, tc))  # neither the assignee nor a manager
    r = other.post(f"/api/tasks/{key}/workflow/pause")
    assert r.status_code == 403 and r.json()["detail"] == "cannot_act_on_workflow", r.text

    ac = await _admin_client(db, tc_factory)
    r = ac.post(f"/api/tasks/{key}/workflow/pause")
    assert r.status_code == 200, r.text
    assert (r.json()["driver"], r.json()["status"], r.json()["needs"]) == ("connect_only", "paused", None)
    [paused] = await _events(task_id, "workflow.paused")
    assert paused.data == {"reason": "manual"}
    r = ac.post(f"/api/tasks/{key}/workflow/pause")
    assert r.status_code == 409 and r.json()["detail"] == "workflow_not_active"

    # the paused workflow no longer holds the assignee: an agent takes it over from brainstorm
    r = ac.patch(f"/api/tasks/{key}", json={"assignee_agent_id": b.agent["id"]})
    assert r.status_code == 200, r.text
    wf = await _wf(task_id)
    assert (wf.driver, wf.status, wf.stage, wf.needs, wf.enforcement, wf.current_step) == (
        "runner", "idle", "brainstorm", None, "enforced", None
    )
    assert [(d.kind, d.version) for d in await _docs(task_id)] == [("design", 1)]  # documents kept
    # and the agent's owner starts it like any agent task
    assert tc.post(f"/api/tasks/{key}/workflow/start").status_code == 200
    assert [(r.workflow_role, r.status) for r in await _task_runs(task_id)] == [("brainstorm", "queued")]


async def test_manager_pauses_a_connect_only_workflow_then_switches_it_to_the_checklist(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _started(db, tc)
    _, key, task_id, _ = await _members_connect_only(db, tc, tc_factory)
    r = tc.post(f"/api/tasks/{key}/workflow/pause")  # tc is the project's manager
    assert r.status_code == 200, r.text
    assert r.json()["can_set_manual"] is True
    r = tc.patch(f"/api/tasks/{key}/workflow", json={"driver": "manual", "stage": "plan"})
    assert r.status_code == 200, r.text
    wf = await _wf(task_id)
    assert (wf.driver, wf.stage, wf.status, wf.enforcement) == ("manual", "plan", "idle", "unenforced")


async def test_the_assignees_next_stage_tool_resumes_a_paused_connect_only_workflow(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _started(db, tc)
    mc, key, task_id, token = await _members_connect_only(db, tc, tc_factory)
    # the assignee may pause their own workflow; get_workflow only reads
    assert mc.post(f"/api/tasks/{key}/workflow/pause").status_code == 200
    assert not _tool(mc, token, "get_workflow", key=key)[0]
    assert (await _wf(task_id)).status == "paused"
    # a stage tool resumes it, back to the approval it was waiting for
    assert not _tool(mc, token, "ask_human", key=key, question="Still there?")[0]
    wf = await _wf(task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "design_approval")
    [resumed] = await _events(task_id, "workflow.resumed")
    assert resumed.actor_user_id is not None
    _answer_open(tc, key, await _questions(task_id), "Yes")
    _approve(tc, key, "design", 1)
    # paused while running: the next stage tool sets it running again and goes through
    assert tc.post(f"/api/tasks/{key}/workflow/pause").status_code == 200
    err, out = _tool(mc, token, "submit_plan", key=key, markdown="# Plan", steps=STEPS)
    assert not err, out
    wf = await _wf(task_id)
    assert (wf.driver, wf.stage, wf.status, wf.needs) == ("connect_only", "plan", "waiting_human", "plan_approval")


async def _task_runs(task_id) -> list[AgentRun]:
    async with SessionLocal() as s:
        rows = await s.execute(select(AgentRun).where(AgentRun.task_id == task_id).order_by(AgentRun.created_at))
        return list(rows.scalars())


async def test_get_document_carries_the_decision_comment_and_who_decided(db, tc_factory):
    """I6: a revising agent can read why its document was rejected, even when it starts a fresh session."""
    tc = tc_factory(lifespan=True)
    b, _ = await _design_waiting(db, tc)
    r = tc.post(f"/api/tasks/{b.key}/documents/design/1/decision", json={"approve": False, "comment": "Simpler"})
    assert r.status_code == 200, r.text
    revision = (await _task_runs(b.task_id))[-1]
    token = await _run_token(revision)
    err, out = _tool(tc, token, "get_document", key=b.key, kind="design", version=1)
    assert not err, out
    assert (out["status"], out["decision_comment"], out["decided_by"]) == ("rejected", "Simpler", str(b.manager.id))
