"""Decision and test-run records (Plan 8 Task 2): what an agent decided on its own, and what its tests said."""

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.workflow.models import WorkflowDecision, WorkflowTestRun
from tests.mcp.test_workflow_tools import (
    ALLOWED,
    _connect_only_building,
    _my_task,
    _personal,
    _run_token,
    _tool,
)
from tests.workflow.test_engine import _events, _finish, _started

DECISION = {"decision": "Used a map", "reason": "Lookups by id", "cost_if_wrong": "One refactor",
            "plan_said": "Use a list"}
TESTS = {"command": "uv run pytest", "passed": True, "total": 3, "failed": 0, "skipped": 0}


async def _as(run, role: str, step: int | None, stage: str) -> None:
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run.id).values(workflow_role=role, step=step, stage=stage))
        await s.commit()


async def _rows(model, task_id) -> list:
    async with SessionLocal() as s:
        rows = await s.execute(select(model).where(model.task_id == task_id).order_by(model.created_at, model.id))
        return list(rows.scalars())


async def _building(db, tc, role="implement", step=2):
    b, run = await _started(db, tc)
    token = await _run_token(run)
    await _as(run, role, step, "build" if step else "done")
    return b, run, token


async def test_record_decision_from_an_implement_run(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run, token = await _building(db, tc)
    err, out = _tool(tc, token, "record_decision", key=b.key, **DECISION)
    assert not err, out
    [row] = await _rows(WorkflowDecision, b.task_id)
    assert str(row.id) == out["id"]
    assert (row.run_id, str(row.agent_id), row.posted_by, row.stage, row.step) == (
        run.id, b.agent["id"], None, "build", 2)
    assert (row.decision, row.reason, row.cost_if_wrong, row.plan_said) == (
        "Used a map", "Lookups by id", "One refactor", "Use a list")
    [event] = await _events(b.task_id, "decision.recorded")
    assert event.data == {"step": 2, "stage": "build", "decision": "Used a map"}
    records = tc.get(f"/api/tasks/{b.key}/records").json()
    [d] = records["decisions"]
    assert (d["decision"], d["plan_said"], d["step"], d["author"]) == ("Used a map", "Use a list", 2, b.agent["name"])
    assert records["test_runs"] == [] and records["unverified_steps"] == []


async def test_record_tests_from_a_finish_run_has_no_step(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _, token = await _building(db, tc, role="finish", step=None)
    err, out = _tool(tc, token, "record_tests", key=b.key, **TESTS, failing=[])
    assert (err, out["passed"]) == (False, True), out
    [row] = await _rows(WorkflowTestRun, b.task_id)
    assert (row.stage, row.step, row.command, row.total, row.failing) == ("done", None, "uv run pytest", 3, [])
    assert await _events(b.task_id, "tests.recorded") == []
    [t] = tc.get(f"/api/tasks/{b.key}/records").json()["test_runs"]
    assert (t["stage"], t["step"], t["passed"], t["author"]) == ("done", None, True, b.agent["name"])


async def test_record_tools_roles(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run, token = await _building(db, tc)
    allowed = {"implement", "step_fix", "final_fix", "finish"}
    assert ALLOWED["record_decision"] == allowed and ALLOWED["record_tests"] == allowed
    for role in ("step_review", "final_review", "brainstorm", "plan"):
        await _as(run, role, 2, "build")
        assert "not_allowed_in_role" in _tool(tc, token, "record_decision", key=b.key, **DECISION)[1], role
        assert "not_allowed_in_role" in _tool(tc, token, "record_tests", key=b.key, **TESTS)[1], role
    assert await _rows(WorkflowDecision, b.task_id) == [] and await _rows(WorkflowTestRun, b.task_id) == []


async def test_record_decision_validation(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _, token = await _building(db, tc)
    assert "invalid_record" in _tool(tc, token, "record_decision", key=b.key, **{**DECISION, "decision": "  "})[1]
    assert "too_large" in _tool(tc, token, "record_decision", key=b.key, **{**DECISION, "reason": "r" * 1001})[1]
    assert "too_large" in _tool(tc, token, "record_decision", key=b.key, **{**DECISION, "cost_if_wrong": "c" * 501})[1]
    assert "too_large" in _tool(tc, token, "record_decision", key=b.key, **{**DECISION, "plan_said": "p" * 1001})[1]
    err, _ = _tool(tc, token, "record_decision", key=b.key, **{**DECISION, "decision": "Used\x00 a map ", "plan_said": None})
    assert not err
    [row] = await _rows(WorkflowDecision, b.task_id)
    assert (row.decision, row.plan_said) == ("Used a map", None)


async def test_record_tests_validation(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _, token = await _building(db, tc)
    for bad in (
        {"failing": [f"t{n}" for n in range(21)]},
        {"failing": [1]},
        {"failing": ["  "]},
        {"passed": "yes"},
        {"total": -1},
        {"failed": True},
        {"command": "  "},
    ):
        err, text = _tool(tc, token, "record_tests", key=b.key, **{**TESTS, **bad})
        assert err and "invalid_record" in text, (bad, text)
    assert "too_large" in _tool(tc, token, "record_tests", key=b.key, **TESTS, failing=["n" * 301])[1]
    assert "too_large" in _tool(tc, token, "record_tests", key=b.key, **{**TESTS, "command": "c" * 201})[1]
    assert await _rows(WorkflowTestRun, b.task_id) == []
    assert not _tool(tc, token, "record_tests", key=b.key, **{**TESTS, "passed": False}, failing=["a\x00b"])[0]
    [row] = await _rows(WorkflowTestRun, b.task_id)
    assert (row.passed, row.failing) == (False, ["ab"])


async def test_caps_per_step(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run, token = await _building(db, tc)
    async with SessionLocal() as s:
        s.add_all(WorkflowDecision(task_id=b.task_id, run_id=run.id, stage="build", step=2, decision="d", reason="r",
                                   cost_if_wrong="c") for _ in range(30))
        s.add_all(WorkflowTestRun(task_id=b.task_id, run_id=run.id, stage="build", step=2, command="c", passed=True,
                                  failing=[]) for _ in range(50))
        await s.commit()
    assert "too_many_records" in _tool(tc, token, "record_decision", key=b.key, **DECISION)[1]
    assert "too_many_records" in _tool(tc, token, "record_tests", key=b.key, **TESTS)[1]
    await _as(run, "implement", 3, "build")
    assert not _tool(tc, token, "record_decision", key=b.key, **DECISION)[0]
    assert not _tool(tc, token, "record_tests", key=b.key, **TESTS)[0]


async def test_connect_only_records_during_build_only(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    user = b.manager
    key, token = await _connect_only_building(tc, user)
    assert not _tool(tc, token, "record_tests", key=key, **TESTS)[0]
    assert not _tool(tc, token, "record_decision", key=key, **DECISION)[0]
    records = tc.get(f"/api/tasks/{key}/records").json()
    [t], [d] = records["test_runs"], records["decisions"]
    assert (t["stage"], t["step"], t["author"]) == ("build", 1, f"{user.name}'s connected agent")
    assert d["author"] == f"{user.name}'s connected agent"
    async with SessionLocal() as s:
        row = (await s.execute(select(WorkflowTestRun).where(WorkflowTestRun.posted_by == user.id))).scalar_one()
    assert (row.run_id, row.agent_id) == (None, None)
    fresh = _my_task(tc, user, "Fresh")["key"]
    assert not _tool(tc, _personal(tc), "ask_human", key=fresh, question="Start?")[0]
    err, text = _tool(tc, token, "record_tests", key=fresh, **TESTS)
    assert err and "wrong_stage" in text


async def test_unverified_steps(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run, token = await _building(db, tc, step=1)

    def claim(step):
        assert not _tool(tc, token, "complete_step", key=b.key, step=step, summary="done", tests_passed=True)[0]

    claim(1)  # no recorded run: unverified
    await _as(run, "implement", 2, "build")
    assert not _tool(tc, token, "record_tests", key=b.key, **TESTS)[0]
    claim(2)  # verified
    await _as(run, "implement", 3, "build")
    assert not _tool(tc, token, "record_tests", key=b.key, **TESTS)[0]
    claim(3)
    claim(3)  # the passing run came before the previous claim: this one is unverified
    assert tc.get(f"/api/tasks/{b.key}/records").json()["unverified_steps"] == [1, 3]


async def test_unverified_steps_connect_only(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    key, token = await _connect_only_building(tc, b.manager)
    assert not _tool(tc, token, "record_tests", key=key, **TESTS)[0]
    assert not _tool(tc, token, "complete_step", key=key, step=1, summary="s", tests_passed=True)[0]
    assert not _tool(tc, token, "complete_step", key=key, step=2, summary="s", tests_passed=True)[0]
    assert tc.get(f"/api/tasks/{key}/records").json()["unverified_steps"] == [2]



async def test_the_queued_step_review_prompt_carries_the_steps_records(db, tc_factory):
    from tests.workflow.test_build import _building as _build_step_1
    from tests.workflow.test_build import _complete, _last

    tc = tc_factory(lifespan=True)
    b, run = await _build_step_1(db, tc)
    token = await _run_token(run)
    assert not _tool(tc, token, "record_decision", key=b.key, **DECISION)[0]
    assert not _tool(tc, token, "record_tests", key=b.key, **TESTS)[0]
    await _complete(run)
    await _finish(b.manager.id, run, "completed", session_id="impl-1")
    review = await _last(b.task_id)
    assert review.workflow_role == "step_review"
    assert "## Decisions the agent recorded" in review.prompt and "Used a map" in review.prompt
    assert "Step 1: passed — uv run pytest (total 3, failed 0, skipped 0)" in review.prompt


async def test_a_run_recorded_while_the_claim_waited_for_the_lock_counts(db, tc_factory):
    """Final review fix: record_tests and complete_step issued in parallel. The claim's transaction starts first
    but takes the lock after the record is in: the step is verified."""
    from app.tasks.models import Task
    from app.workflow import build, records
    from app.workflow.models import TaskWorkflow

    tc = tc_factory(lifespan=True)
    b, run, _ = await _building(db, tc, step=1)
    async with SessionLocal() as claim:
        await claim.execute(select(AgentRun.id).limit(1))  # the claim's transaction has started
        async with SessionLocal() as rec:
            task = await rec.get(Task, b.task_id)
            await records.record_tests(rec, task, await rec.get(TaskWorkflow, b.task_id), run=await rec.get(AgentRun, run.id),
                                       posted_by=None, command="pytest", passed=True)
            await rec.commit()
        await build.complete_step(claim, await claim.get(AgentRun, run.id), 1, "done", True, "pytest")
        await claim.commit()
    async with SessionLocal() as s:
        assert await records.unverified_steps(s, b.task_id) == []
