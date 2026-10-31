"""Workflow engine core: start, pause, resume, board rules, run outcomes (Task 6)."""

import asyncio
import time
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.agent_runs.models import AgentRun
from app.agent_runs.service import finish_run
from app.auth.models import User
from app.core.db import SessionLocal
from app.runner.protocol import runner_message
from app.runner.registry import WORKFLOW_PROBLEM
from app.tasks.models import Task, TaskEvent
from app.teams.models import TeamMember
from app.workflow import engine, methodology
from app.workflow.models import (
    DocKind,
    QuestionStatus,
    TaskWorkflow,
    WorkflowDocument,
    WorkflowQuestion,
)
from tests.agent_runs.test_dispatch import _avail, _setup
from tests.agent_runs.test_run_guards import _next_of
from tests.factories import make_user
from tests.runner.test_runner_ws import (
    URL,
    _agent,
    _hello,
    _login,
    _manager_with_project,
    _wait_status,
)

SHA_A, SHA_B = "a" * 40, "b" * 40


class Board:
    def __init__(self, tc, manager, token, agent, task, cols):
        self.tc, self.manager, self.token, self.agent, self.task, self.cols = tc, manager, token, agent, task, cols

    @property
    def key(self) -> str:
        return self.task["key"]

    @property
    def task_id(self) -> uuid.UUID:
        return uuid.UUID(self.task["id"])


async def _board(db, tc) -> Board:
    """A manager owning a bound agent, a task assigned to it, and the first column of each category."""
    manager, _ = await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    cols: dict[str, dict] = {}
    for c in sorted(tc.get("/api/projects/PAY/columns").json(), key=lambda c: c["position"]):
        cols.setdefault(c["category"], c)
    return Board(tc, manager, token, agent, task, cols)


async def _member(db, tc) -> User:
    """A plain member of the project's team: neither the agent's owner nor a manager."""
    user = await make_user(db)
    team_id = tc.get("/api/projects/PAY").json()["team_ids"][0]
    db.add(TeamMember(team_id=uuid.UUID(team_id), user_id=user.id))
    await db.commit()
    return user


def _move(tc, key, col):
    return tc.post(f"/api/tasks/{key}/move", json={"column_id": col["id"]})


def _hello_v2(agent):
    return _hello([_avail(agent)])


async def _runs(task_id) -> list[AgentRun]:
    async with SessionLocal() as s:
        rows = await s.execute(
            select(AgentRun).where(AgentRun.task_id == task_id).order_by(AgentRun.created_at, AgentRun.id)
        )
        return list(rows.scalars())


async def _wf(task_id) -> TaskWorkflow:
    async with SessionLocal() as s:
        return await s.get(TaskWorkflow, task_id)


async def _kinds(task_id) -> list[str]:
    async with SessionLocal() as s:
        rows = await s.execute(
            select(TaskEvent.kind).where(TaskEvent.task_id == task_id).order_by(TaskEvent.created_at, TaskEvent.id)
        )
        return [k for (k,) in rows.all()]


async def _events(task_id, kind) -> list[TaskEvent]:
    async with SessionLocal() as s:
        rows = await s.execute(select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.kind == kind))
        return list(rows.scalars())


async def _until(check, what="condition"):
    deadline = time.monotonic() + 5
    while not await check():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        await asyncio.sleep(0.02)


async def _finish(owner_id, run, outcome="completed", **v2):
    """The runner reports the end of `run` (marked running first, as if dispatched)."""
    async with SessionLocal() as s:
        await s.execute(
            update(AgentRun).where(AgentRun.id == run.id).values(status="running", started_at=datetime.now(UTC))
        )
        await s.commit()
    msg = runner_message.validate_python(
        {"type": "run_finished", "run_id": str(run.id), "outcome": outcome, "summary": "", **v2}
    )
    async with SessionLocal() as s:
        await finish_run(s, owner_id, run.id, outcome, "", None, msg)


async def _started(db, tc) -> tuple[Board, AgentRun]:
    b = await _board(db, tc)
    assert _move(tc, b.key, b.cols["working"]).status_code == 200
    [run] = await _runs(b.task_id)
    return b, run


async def _ask(task_id, run_id) -> uuid.UUID:
    """What Task 7's ask_human leaves behind: an open question from this run."""
    async with SessionLocal() as s:
        q = WorkflowQuestion(task_id=task_id, run_id=run_id, stage="brainstorm", body="Which DB?", choices=[])
        s.add(q)
        await s.commit()
        return q.id


async def _submit(task_id, run_id, kind: str, version: int = 1) -> None:
    """What Task 8's submit leaves behind: a submitted document from this run."""
    async with SessionLocal() as s:
        steps = [{"title": "One", "detail": "d", "subtask_id": None}] if kind == "plan" else None
        s.add(WorkflowDocument(task_id=task_id, kind=DocKind(kind), version=version, body_md=f"{kind} v{version}",
                               steps=steps, submitted_run_id=run_id))
        await s.commit()


# ---- board rules --------------------------------------------------------------


async def test_moving_agent_task_into_working_starts_brainstorm_run(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    r = _move(tc, b.key, b.cols["working"])
    assert r.status_code == 200, r.text
    assert r.json()["workflow"]["status"] == "running" and r.json()["workflow"]["stage"] == "brainstorm"
    [run] = await _runs(b.task_id)
    assert (run.workflow_role, run.stage, run.status, run.policy) == ("brainstorm", "brainstorm", "queued", "read_only")
    meth = await methodology.current(db, "brainstorm")
    assert run.prompt.startswith(meth.body_md.rstrip()) and run.methodology_version_id == meth.id
    assert run.requested_by == b.manager.id and run.resume_session_ref is None
    wf = await _wf(b.task_id)
    assert (wf.driver, wf.enforcement, str(wf.agent_id)) == ("runner", "enforced", b.agent["id"])
    kinds = await _kinds(b.task_id)
    assert "workflow.started" in kinds and "agent_run_queued" in kinds
    out = tc.get(f"/api/tasks/{b.key}/workflow").json()
    assert out["status"] == "running" and out["needs"] is None and out["finishing_option"] == "pull_request"
    assert out["finishing_forced"] is False and out["can_set_manual"] is False
    [listed] = tc.get(f"/api/tasks/{b.key}/agent-runs").json()
    assert (listed["workflow_role"], listed["step"]) == ("brainstorm", None)
    # moving within working, or into working again, starts nothing more
    assert _move(tc, b.key, b.cols["working"]).status_code == 200
    assert len(await _runs(b.task_id)) == 1
    r = tc.post(f"/api/tasks/{b.key}/workflow/start")
    assert r.status_code == 409 and r.json()["detail"] == "workflow_active"


async def test_move_refused_for_member_who_cannot_use_agent_403(db, tc_factory):
    tc, other = tc_factory(lifespan=True), tc_factory()
    b = await _board(db, tc)
    member = await _member(db, tc)
    _login(other, member)
    r = _move(other, b.key, b.cols["working"])
    assert r.status_code == 403 and r.json()["detail"] == "cannot_use_agent"
    assert tc.get(f"/api/tasks/{b.key}").json()["column_id"] == b.task["column_id"]
    assert await _runs(b.task_id) == [] and await _wf(b.task_id) is None


async def test_move_to_before_column_pauses_and_cancels_run(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    r = _move(tc, b.key, b.cols["before"])
    assert r.status_code == 200, r.text
    assert r.json()["workflow"]["status"] == "paused"
    [cancelled] = await _runs(b.task_id)
    assert cancelled.id == run.id and cancelled.status == "cancelled" and cancelled.cancelled_by == b.manager.id
    paused = await _events(b.task_id, "workflow.paused")
    assert len(paused) == 1 and paused[0].actor_user_id == b.manager.id
    # back into working resumes it: one new run of the same role
    r = _move(tc, b.key, b.cols["working"])
    assert r.status_code == 200 and r.json()["workflow"]["status"] == "running"
    runs = await _runs(b.task_id)
    assert [(x.workflow_role, x.status) for x in runs] == [("brainstorm", "cancelled"), ("brainstorm", "queued")]
    assert "workflow.resumed" in await _kinds(b.task_id)


async def test_human_cannot_drag_active_workflow_into_review_or_done_409(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run = await _started(db, tc)
    for cat in ("review", "done"):
        r = _move(tc, b.key, b.cols[cat])
        assert r.status_code == 409 and r.json()["detail"] == "workflow_controls_column", cat
    assert tc.post(f"/api/tasks/{b.key}/workflow/pause").status_code == 200
    r = _move(tc, b.key, b.cols["done"])  # paused is still not finished
    assert r.status_code == 409 and r.json()["detail"] == "workflow_controls_column"
    # a task without a workflow moves freely
    plain = tc.post("/api/projects/PAY/tasks", json={"title": "Plain"}).json()
    assert _move(tc, plain["key"], b.cols["done"]).status_code == 200


async def test_engine_moves_card_with_by_workflow(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run = await _started(db, tc)
    async with SessionLocal() as s:
        task = await s.get(Task, b.task_id)
        await engine.move_to_category(s, task, "review")
        await s.commit()
    assert tc.get(f"/api/tasks/{b.key}").json()["column_id"] == b.cols["review"]["id"]
    # the same kind as a human move, so the activity thread shows it
    [moved] = [e for e in await _events(b.task_id, "status_changed") if e.data.get("by") == "workflow"]
    assert moved.actor_user_id is None
    assert moved.data["to_column"] == b.cols["review"]["id"] and moved.data["to_category"] == "review"
    assert await _events(b.task_id, "moved") == []


async def test_reassign_agent_while_active_409_and_paused_clears_sessions(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run = await _started(db, tc)
    other = _agent(tc, name="Other")
    r = tc.put(f"/api/agents/{other['id']}/bindings", json={"bindings": [{"project_ref": "PAY", "local_path": "/o"}]})
    assert r.status_code == 200
    await db.execute(update(TaskWorkflow).values(sessions={"brainstorm": "s-1", "implement:1": "s-2"}))
    await db.commit()
    r = tc.patch(f"/api/tasks/{b.key}", json={"assignee_agent_id": other["id"]})
    assert r.status_code == 409 and r.json()["detail"] == "workflow_active"
    r = tc.patch(f"/api/tasks/{b.key}", json={"assignee_user_id": str(b.manager.id)})
    assert r.status_code == 409 and r.json()["detail"] == "workflow_active"
    assert tc.patch(f"/api/tasks/{b.key}", json={"title": "Renamed"}).status_code == 200  # other edits are fine
    assert tc.post(f"/api/tasks/{b.key}/workflow/pause").json()["status"] == "paused"
    r = tc.patch(f"/api/tasks/{b.key}", json={"assignee_agent_id": other["id"]})
    assert r.status_code == 200, r.text
    wf = await _wf(b.task_id)
    assert wf.sessions == {} and str(wf.agent_id) == other["id"]
    # resuming runs on the new agent, fresh
    r = tc.post(f"/api/tasks/{b.key}/workflow/resume")
    assert r.status_code == 200, r.text
    last = (await _runs(b.task_id))[-1]
    assert str(last.agent_id) == other["id"] and last.resume_session_ref is None


# ---- run outcomes -------------------------------------------------------------


async def test_failed_run_retried_then_escalates_after_three(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    for n in (1, 2):
        await _finish(b.manager.id, run, "failed")
        runs = await _runs(b.task_id)
        assert len(runs) == n + 1 and runs[-1].status == "queued" and runs[-1].workflow_role == "brainstorm"
        assert (await _wf(b.task_id)).failures == n
        run = runs[-1]
    await _finish(b.manager.id, run, "failed")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason, wf.failures) == (
        "waiting_human", "escalation", "retries_exhausted", 3)
    assert len(await _runs(b.task_id)) == 3  # no fourth attempt
    [esc] = await _events(b.task_id, "workflow.escalated")
    assert esc.data == {"reason": "retries_exhausted"}
    # a second report of the same end changes nothing (idempotent per run)
    async with SessionLocal() as s:
        await engine.on_run_finished(s, await s.get(AgentRun, run.id))
        await s.commit()
    assert (await _wf(b.task_id)).failures == 3 and len(await _runs(b.task_id)) == 3
    # the human decides: accept is not allowed here, retry runs the role again with a fresh failure count
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "accept"})
    assert r.status_code == 422 and r.json()["detail"] == "cannot_accept_here"
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "retry"})
    assert r.status_code == 200 and r.json()["status"] == "running"
    wf = await _wf(b.task_id)
    assert wf.failures == 0 and wf.escalation_reason is None
    assert [x.status for x in await _runs(b.task_id)][-1] == "queued"
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "retry"})
    assert r.status_code == 409 and r.json()["detail"] == "already_decided"


async def test_completed_run_resets_failures_and_retry_resumes_stored_session(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _finish(b.manager.id, run, "failed", session_id="sess-1")
    retry = (await _runs(b.task_id))[-1]
    assert retry.resume_session_ref == "sess-1" and retry.resume_prompt
    assert (await _wf(b.task_id)).sessions == {"brainstorm": "sess-1"}
    await _ask(b.task_id, retry.id)
    await _finish(b.manager.id, retry, "completed")
    wf = await _wf(b.task_id)
    assert (wf.failures, wf.status, wf.needs) == (0, "waiting_human", "question")


async def test_disconnect_mid_run_resumes_same_role_on_reconnect(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    assert _move(tc, b.key, b.cols["working"]).status_code == 200
    with tc.websocket_connect(URL, headers=b.token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(b.agent))
        first = _next_of(ws, "run_start")
        assert first["role"] == "brainstorm" and first["resume_session_id"] is None
        await _ask(b.task_id, uuid.UUID(first["run_id"]))  # the agent asks and ends its turn
        ws.send_json({"type": "run_finished", "run_id": first["run_id"], "outcome": "completed", "summary": "asked",
                      "session_id": "sess-1"})

        async def waiting():
            return (await _wf(b.task_id)).needs == "question"

        await _until(waiting, "the question wait")
    # the human answers (Task 7 does this through questions.answer): the brainstorm session resumes
    async with SessionLocal() as s:
        wf = await engine.lock_workflow(s, b.task_id)
        task = await s.get(Task, b.task_id)
        await s.execute(update(WorkflowQuestion).values(status=QuestionStatus.answered))
        await engine.enqueue(s, wf, task, "brainstorm", resume_kind="answer", payload={"text": "Use Postgres"},
                             requested_by=b.manager.id)
        await s.commit()
    with tc.websocket_connect(URL, headers=b.token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(b.agent))
        second = _next_of(ws, "run_start")
        assert second["resume_session_id"] == "sess-1" and "Use Postgres" in second["resume_prompt"]
    # the runner dropped mid-run

    async def second_failed():
        return [r.status for r in await _runs(b.task_id)][1] == "failed"

    await _until(second_failed, "the dropped run to fail")
    runs = await _runs(b.task_id)
    assert runs[1].reason == "runner_disconnected" and runs[2].status == "queued"
    with tc.websocket_connect(URL, headers=b.token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(b.agent))
        third = _next_of(ws, "run_start")
        assert third["run_id"] == str(runs[2].id) and third["role"] == "brainstorm"
        assert third["resume_session_id"] == "sess-1" and "Use Postgres" in third["resume_prompt"]
        ws.send_json(_hello_v2(b.agent))  # more hellos start nothing more
        ws.send_json({"type": "heartbeat"})
        _wait_status(tc, b.agent["id"], "busy")
        statuses = [r.status for r in await _runs(b.task_id)]
        assert statuses == ["completed", "failed", "running"]
        assert (await _wf(b.task_id)).failures == 1


async def test_brainstorm_without_output_is_nudged_once_then_escalates(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _finish(b.manager.id, run, "completed", session_id="sess-1")  # no git report: no check
    wf = await _wf(b.task_id)
    assert wf.nudged and wf.status == "running" and wf.enforcement == "enforced"
    nudge = (await _runs(b.task_id))[-1]
    assert nudge.workflow_role == "brainstorm" and nudge.resume_session_ref == "sess-1"
    assert "submit_design" in nudge.resume_prompt
    await _finish(b.manager.id, nudge, "completed")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "no_output")
    assert len(await _runs(b.task_id)) == 2


async def test_brainstorm_design_and_plan_outputs(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _submit(b.task_id, run.id, "design")
    await _finish(b.manager.id, run, "completed")
    wf = await _wf(b.task_id)
    assert (wf.stage, wf.status, wf.needs) == ("design", "waiting_human", "design_approval")
    [stage] = await _events(b.task_id, "workflow.stage")
    assert stage.data == {"from": "brainstorm", "to": "design"}
    out = tc.get(f"/api/tasks/{b.key}/workflow").json()
    assert out["documents"] == [{"kind": "design", "version": 1, "status": "submitted"}]
    # what Task 8's approval does: the plan stage starts with a fresh plan run
    async with SessionLocal() as s:
        wf = await engine.lock_workflow(s, b.task_id)
        task = await s.get(Task, b.task_id)
        await engine.set_stage(s, wf, task, "plan")
        plan_run = await engine.enqueue(s, wf, task, "plan", requested_by=b.manager.id)
        await s.commit()
    assert plan_run.policy == "read_only" and plan_run.stage == "plan"
    await _submit(b.task_id, plan_run.id, "plan")
    await _finish(b.manager.id, plan_run, "completed")
    wf = await _wf(b.task_id)
    assert (wf.stage, wf.status, wf.needs) == ("plan", "waiting_human", "plan_approval")


@pytest.mark.parametrize("after", [{"head": SHA_B, "dirty": False}, {"head": SHA_A, "dirty": True}])
async def test_git_change_in_read_only_stage_marks_partially_enforced_and_escalates(db, tc_factory, after):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _submit(b.task_id, run.id, "design")
    await _finish(b.manager.id, run, "completed",
                  git_before={"head": SHA_A, "branch": "megoo/PAY-1", "dirty": False},
                  git_after={"branch": "megoo/PAY-1", **after})
    wf = await _wf(b.task_id)
    assert wf.enforcement == "partially_enforced"
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "enforcement_violation")
    [violation] = await _events(b.task_id, "enforcement.violation")
    assert violation.data == {"stage": "brainstorm", "role": "brainstorm"}
    assert tc.get(f"/api/tasks/{b.key}").json()["workflow"]["enforcement"] == "partially_enforced"
    # accept: the workflow continues with the run's output, and stays partially enforced
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "accept"})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["needs"], r.json()["enforcement"]) == (
        "waiting_human", "design_approval", "partially_enforced")


async def test_escalation_pause_and_actor_rights(db, tc_factory):
    tc, other = tc_factory(lifespan=True), tc_factory()
    b, _run = await _started(db, tc)
    async with SessionLocal() as s:
        wf = await engine.lock_workflow(s, b.task_id)
        await engine.escalate(s, wf, "no_output")
        await s.commit()
    stranger = await _member(db, tc)
    _login(other, stranger)
    r = other.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "pause"})
    assert r.status_code == 403 and r.json()["detail"] == "cannot_act_on_workflow"
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "pause"})
    assert r.status_code == 200 and r.json()["status"] == "paused" and r.json()["escalation_reason"] is None
    decided = await _events(b.task_id, "escalation.decided")
    assert [e.data for e in decided] == [{"action": "pause", "reason": "no_output"}]


async def test_cancelling_a_workflow_run_pauses_the_workflow(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    assert tc.post(f"/api/agent-runs/{run.id}/cancel").status_code == 204
    wf = await _wf(b.task_id)
    assert wf.status == "paused" and wf.failures == 0
    assert len(await _runs(b.task_id)) == 1  # never retried
    r = tc.post(f"/api/tasks/{b.key}/workflow/resume")
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert len(await _runs(b.task_id)) == 2


async def test_session_reported_after_pause_is_resumed(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await db.execute(update(AgentRun).where(AgentRun.id == run.id).values(status="running"))
    await db.commit()
    assert tc.post(f"/api/tasks/{b.key}/workflow/pause").status_code == 200  # no runner: cancelled at once
    # the runner's late report of the cancelled run still carries its session
    msg = runner_message.validate_python({"type": "run_finished", "run_id": str(run.id), "outcome": "cancelled",
                                          "summary": "", "session_id": "sess-9"})
    async with SessionLocal() as s:
        await finish_run(s, b.manager.id, run.id, "cancelled", "", None, msg)
    wf = await _wf(b.task_id)
    assert wf.status == "paused" and wf.sessions == {"brainstorm": "sess-9"} and wf.failures == 0
    assert tc.post(f"/api/tasks/{b.key}/workflow/resume").status_code == 200
    resumed = (await _runs(b.task_id))[-1]
    assert resumed.resume_session_ref == "sess-9" and resumed.resume_prompt


async def test_engine_error_escalates_without_undoing_the_run_end(db, tc_factory, monkeypatch):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)

    async def broken(*_args):
        raise RuntimeError("boom")

    monkeypatch.setitem(engine.ROLE_HANDLERS, engine.RunRole.brainstorm, broken)
    await _finish(b.manager.id, run, "completed")
    [ended] = await _runs(b.task_id)
    assert ended.status == "completed"
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "engine_error")


async def test_runner_side_cancel_is_treated_as_failure(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _finish(b.manager.id, run, "cancelled")
    wf = await _wf(b.task_id)
    assert wf.failures == 1 and wf.status == "running"
    assert [r.status for r in await _runs(b.task_id)] == ["cancelled", "queued"]


async def test_pause_while_waiting_resumes_into_the_same_wait(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _ask(b.task_id, run.id)
    await _finish(b.manager.id, run, "completed")
    assert tc.post(f"/api/tasks/{b.key}/workflow/pause").json()["status"] == "paused"
    r = tc.post(f"/api/tasks/{b.key}/workflow/resume")
    assert (r.json()["status"], r.json()["needs"]) == ("waiting_human", "question")
    assert r.json()["open_question_id"] is not None
    assert len(await _runs(b.task_id)) == 1


async def test_old_runner_without_capability_keeps_run_queued(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    with tc.websocket_connect(URL, headers=b.token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(b.agent)], capabilities=["branch/1", "model/1"]))  # a runner without workflow/1
        _wait_status(tc, b.agent["id"], "online")
        mine = next(a for a in tc.get("/api/agents/mine").json() if a["id"] == b.agent["id"])
        assert mine["problems"] == [WORKFLOW_PROBLEM]
        assert [r.status for r in await _runs(b.task_id)] == ["queued"]
        ws.send_json(_hello_v2(b.agent))  # updated: now it gets the run
        assert _next_of(ws, "run_start")["run_id"] == str(run.id)


# ---- start guards, manual driver, the removed endpoint --------------------------


async def test_start_guards(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    plain = tc.post("/api/projects/PAY/tasks", json={"title": "Plain"}).json()
    r = tc.post(f"/api/tasks/{plain['key']}/workflow/start")
    assert r.status_code == 422 and r.json()["detail"] == "task_not_assigned_to_agent"
    r = tc.post(f"/api/tasks/{b.key}/workflow/start")
    assert r.status_code == 200 and r.json()["status"] == "running"
    r = tc.post(f"/api/tasks/{b.key}/workflow/resume")
    assert r.status_code == 409 and r.json()["detail"] == "workflow_not_paused"
    # the engine's own run guard: one active run per task
    async with SessionLocal() as s:
        wf = await engine.lock_workflow(s, b.task_id)
        task = await s.get(Task, b.task_id)
        with pytest.raises(HTTPException) as exc:
            await engine.enqueue(s, wf, task, "brainstorm", requested_by=b.manager.id)
    assert exc.value.status_code == 409 and exc.value.detail == "task_has_active_run"


async def test_manual_driver_checklist_sets_stage_without_runs(db, tc_factory):
    tc, other = tc_factory(lifespan=True), tc_factory()
    b = await _board(db, tc)
    member = await _member(db, tc)
    mine = tc.post("/api/projects/PAY/tasks", json={"title": "Mine", "assignee_user_id": str(member.id)}).json()
    _login(other, member)
    r = other.patch(f"/api/tasks/{mine['key']}/workflow", json={"driver": "manual", "stage": "plan"})
    assert r.status_code == 200, r.text
    assert (r.json()["driver"], r.json()["stage"], r.json()["enforcement"]) == ("manual", "plan", "unenforced")
    r = other.patch(f"/api/tasks/{mine['key']}/workflow", json={"driver": "manual", "stage": "done"})
    assert r.status_code == 200 and r.json()["status"] == "finished"
    assert await _runs(uuid.UUID(mine["id"])) == []
    stages = await _events(uuid.UUID(mine["id"]), "workflow.stage")
    assert [e.data for e in stages] == [{"from": "brainstorm", "to": "plan"}, {"from": "plan", "to": "done"}]
    # manual checklists do not hold the card: it moves freely
    assert _move(other, mine["key"], b.cols["done"]).status_code == 200
    # an agent-assigned task cannot be manual; someone else's task needs a manager
    r = tc.patch(f"/api/tasks/{b.key}/workflow", json={"driver": "manual", "stage": "plan"})
    assert r.status_code == 422 and r.json()["detail"] == "task_assigned_to_agent"
    theirs = tc.post("/api/projects/PAY/tasks", json={"title": "Theirs"}).json()
    r = other.patch(f"/api/tasks/{theirs['key']}/workflow", json={"driver": "manual", "stage": "plan"})
    assert r.status_code == 403 and r.json()["detail"] == "cannot_act_on_workflow"
    r = tc.patch(f"/api/tasks/{theirs['key']}/workflow", json={"driver": "manual", "stage": "build"})
    assert r.status_code == 200  # a manager may


async def test_manual_run_endpoint_removed(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    r = tc.post(f"/api/tasks/{b.key}/agent-runs", json={"policy": "workspace", "prompt": "do anything"})
    assert r.status_code in (404, 405)
    assert tc.get(f"/api/tasks/{b.key}/agent-runs").status_code == 200
    assert await _runs(b.task_id) == []


def test_git_state_accepts_sha256_and_truncates_branch():
    msg = runner_message.validate_python({
        "type": "run_finished", "run_id": str(uuid.uuid4()), "outcome": "completed", "summary": "",
        "git_after": {"head": "c" * 64, "branch": "b\u0000" + "x" * 300, "dirty": False},
    })
    assert msg.git_after.head == "c" * 64 and msg.git_after.branch == "b" + "x" * 199
    for bad in ("c" * 63, "C" * 40, "c" * 41):
        with pytest.raises(ValueError):
            runner_message.validate_python({
                "type": "run_finished", "run_id": str(uuid.uuid4()), "outcome": "completed", "summary": "",
                "git_after": {"head": bad, "dirty": False},
            })


# ---- review round 1 -------------------------------------------------------------


async def _admin_client(db, tc_factory):
    from app.auth.models import Role

    ac = tc_factory()
    _login(ac, await make_user(db, role=Role.admin))
    return ac


async def test_owner_deactivated_mid_run_pauses_without_retry(db, tc_factory):
    tc = tc_factory(lifespan=True)
    ac = await _admin_client(db, tc_factory)
    b, run = await _started(db, tc)
    await db.execute(update(AgentRun).where(AgentRun.id == run.id).values(status="running"))
    await db.commit()
    assert ac.post(f"/api/admin/users/{b.manager.id}/deactivate").status_code == 204
    wf = await _wf(b.task_id)
    assert wf.status == "paused" and wf.failures == 0
    assert [(r.status, r.reason) for r in await _runs(b.task_id)] == [("cancelled", "user_deactivated")]
    [paused] = await _events(b.task_id, "workflow.paused")
    assert paused.data == {"reason": "owner_deactivated"} and paused.actor_user_id is None


async def _requester(db, tc, rc):
    """A second manager of the project, logged in on `rc`: may start workflows on the owner's agent."""
    from app.auth.models import Role

    requester = await make_user(db, role=Role.manager)
    team_id = tc.get("/api/projects/PAY").json()["team_ids"][0]
    db.add(TeamMember(team_id=uuid.UUID(team_id), user_id=requester.id))
    await db.commit()
    _login(rc, requester)
    return requester


class _LimitOneRunner:
    """A fake runner holding at most one run per agent, like the real one with max_concurrent_runs = 1: a
    run_start that arrives while it still holds a run is answered `failed` with error `busy`."""

    def __init__(self, ws):
        self.ws, self.holding, self.busy = ws, set(), []

    def next(self, kind: str) -> dict:
        while True:
            msg = _next_of_any(self.ws)
            if msg["type"] == "run_start":
                if self.holding:
                    self.busy.append(msg["run_id"])
                    self.ws.send_json({"type": "run_finished", "run_id": msg["run_id"], "outcome": "failed",
                                       "summary": "", "error": "busy"})
                    continue
                self.holding.add(msg["run_id"])
            if msg["type"] == kind:
                return msg

    def finish(self, run_id: str, outcome: str) -> None:
        self.holding.discard(run_id)
        self.ws.send_json({"type": "run_finished", "run_id": run_id, "outcome": outcome, "summary": ""})


def _next_of_any(ws) -> dict:
    while True:
        msg = ws.receive_json()
        if msg["type"] not in {"welcome", "config_changed"}:
            return msg


async def test_requester_deactivated_running_run_retries_after_the_runner_confirms(db, tc_factory):
    tc, rc = tc_factory(lifespan=True), tc_factory()
    ac = await _admin_client(db, tc_factory)
    b = await _board(db, tc)
    requester = await _requester(db, tc, rc)
    with tc.websocket_connect(URL, headers=b.token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(b.agent))
        _wait_status(tc, b.agent["id"], "online")
        runner = _LimitOneRunner(ws)
        assert _move(rc, b.key, b.cols["working"]).status_code == 200  # a manager starts it on the owner's agent
        first = runner.next("run_start")
        assert ac.post(f"/api/admin/users/{requester.id}/deactivate").status_code == 204
        assert runner.next("run_cancel")["run_id"] == first["run_id"]
        # the runner still holds the run: it stays running, and nothing else is sent to the runner
        assert [r.status for r in await _runs(b.task_id)] == ["running"]
        runner.finish(first["run_id"], "cancelled")  # the runner confirms the cancel
        retry = runner.next("run_start")
        assert retry["run_id"] != first["run_id"] and retry["role"] == "brainstorm"
        assert runner.busy == []
        runs = await _runs(b.task_id)
        assert [r.status for r in runs] == ["cancelled", "running"]  # exactly one retry
        assert runs[1].requested_by == b.manager.id
        wf = await _wf(b.task_id)
        assert (wf.status, wf.failures) == ("running", 1)
        assert all(e.data.get("reason") != "agent_error" for e in await _events(b.task_id, "agent_run_failed"))


async def test_requester_deactivated_queued_run_is_cancelled_and_retried(db, tc_factory):
    tc, rc = tc_factory(lifespan=True), tc_factory()
    ac = await _admin_client(db, tc_factory)
    b = await _board(db, tc)
    requester = await _requester(db, tc, rc)
    assert _move(rc, b.key, b.cols["working"]).status_code == 200  # no runner: the run waits queued
    assert ac.post(f"/api/admin/users/{requester.id}/deactivate").status_code == 204
    runs = await _runs(b.task_id)
    assert [(r.status, r.reason) for r in runs] == [("cancelled", "user_deactivated"), ("queued", None)]
    assert runs[1].requested_by == b.manager.id and (await _wf(b.task_id)).status == "running"


async def test_failed_read_only_run_that_changed_git_escalates_instead_of_retrying(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _finish(b.manager.id, run, "failed",
                  git_before={"head": SHA_A, "branch": "megoo/PAY-1", "dirty": False},
                  git_after={"head": SHA_B, "branch": "megoo/PAY-1", "dirty": False})
    wf = await _wf(b.task_id)
    assert wf.enforcement == "partially_enforced" and wf.escalation_reason == "enforcement_violation"
    assert wf.failures == 0 and len(await _runs(b.task_id)) == 1  # not retried
    [violation] = await _events(b.task_id, "enforcement.violation")
    assert violation.data == {"stage": "brainstorm", "role": "brainstorm"}


async def test_design_submitted_while_paused_waits_for_approval_on_resume(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    with tc.websocket_connect(URL, headers=b.token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(b.agent))
        assert _next_of(ws, "run_start")["run_id"] == str(run.id)
        assert tc.post(f"/api/tasks/{b.key}/workflow/pause").status_code == 200
        assert _next_of(ws, "run_cancel")["run_id"] == str(run.id)
        # the agent had already submitted its design and finishes before the cancel lands
        await _submit(b.task_id, run.id, "design")
        ws.send_json({"type": "run_finished", "run_id": str(run.id), "outcome": "completed", "summary": "done"})

        async def ended():
            return (await _runs(b.task_id))[0].status == "completed"

        await _until(ended, "the run to complete")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.stage) == ("paused", "brainstorm")  # its handling waited for the resume
    r = tc.post(f"/api/tasks/{b.key}/workflow/resume")
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["needs"], r.json()["stage"]) == ("waiting_human", "design_approval", "design")
    assert len(await _runs(b.task_id)) == 1  # nothing re-run
    [stage] = await _events(b.task_id, "workflow.stage")
    assert stage.data == {"from": "brainstorm", "to": "design"}


async def test_nudge_without_a_session_is_appended_to_the_prompt(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _finish(b.manager.id, run, "completed")  # no session reported (an old runner, or none kept)
    nudge = (await _runs(b.task_id))[-1]
    assert nudge.resume_session_ref is None and nudge.resume_prompt is None
    assert nudge.prompt.rstrip().endswith(
        "ask the human with ask_human, or submit your design with submit_design."
    )
    assert len(nudge.prompt) <= 60_000


async def test_member_who_cannot_use_agent_cannot_resume_by_dragging_403(db, tc_factory):
    tc, other = tc_factory(lifespan=True), tc_factory()
    b, _run = await _started(db, tc)
    assert _move(tc, b.key, b.cols["before"]).json()["workflow"]["status"] == "paused"
    _login(other, await _member(db, tc))
    r = _move(other, b.key, b.cols["working"])
    assert r.status_code == 403 and r.json()["detail"] == "cannot_use_agent"
    assert (await _wf(b.task_id)).status == "paused"
    assert tc.get(f"/api/tasks/{b.key}").json()["column_id"] == b.cols["before"]["id"]
    assert len(await _runs(b.task_id)) == 1


async def test_duplicate_run_finished_frame_enqueues_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _finish(b.manager.id, run, "failed")
    msg = runner_message.validate_python(
        {"type": "run_finished", "run_id": str(run.id), "outcome": "failed", "summary": ""}
    )
    async with SessionLocal() as s:  # the runner resends the same frame
        await finish_run(s, b.manager.id, run.id, "failed", "", None, msg)
    assert [r.status for r in await _runs(b.task_id)] == ["failed", "queued"]
    assert (await _wf(b.task_id)).failures == 1
