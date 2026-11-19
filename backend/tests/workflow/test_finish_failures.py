"""Finish runs report their failing tests (MC-97): report_finish's failures and report_test_failures."""

import pytest
from fastapi import HTTPException

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.workflow import engine, finish
from tests.workflow.test_engine import _wf
from tests.workflow.test_build import _last, _review
from tests.workflow.test_engine import _finish
from tests.workflow.test_review_done import PR_URL, _final_review, _patch_project, _report, _to_finish

NEW = {"name": "e2e/a.spec.ts:3", "kind": "new"}
BASE = {"name": "e2e/mobile.spec.ts:98", "kind": "base"}
FLAKY = {"name": "e2e/freestyle.spec.ts:80", "kind": "flaky"}


async def _fail_report(run, failures, *, total=None, tests_passed=False):
    """report_finish with failing tests: the finish delivered all the same."""
    async with SessionLocal() as s:
        await finish.report_finish(s, await s.get(AgentRun, run.id), "pr_opened", "megoo/PAY-1", PR_URL,
                                   tests_passed, failures=failures, failing_total=total)
        await s.commit()


async def _test_failures(run, failures, diagnosis="It fails because the layout overflows.", total=None):
    """report_test_failures: the finish delivered nothing, a person decides."""
    async with SessionLocal() as s:
        await finish.report_test_failures(s, await s.get(AgentRun, run.id), failures, diagnosis, total)
        await s.commit()


async def _code(call, *args, **kw):
    with pytest.raises(HTTPException) as e:
        await call(*args, **kw)
    return e.value.status_code, e.value.detail


async def _run(run_id) -> AgentRun:
    async with SessionLocal() as s:
        return await s.get(AgentRun, run_id)


async def test_report_finish_stores_failures(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _fail_report(run, [NEW, {"name": " e2e/b.spec.ts:9\x00 ", "kind": "base"}, FLAKY], total=5)
    wf = await _wf(b.task_id)
    assert wf.finish_tests == {
        "failures": [NEW, {"name": "e2e/b.spec.ts:9", "kind": "base"}, FLAKY], "failing_total": 5,
        "diagnosis": None, "delivered": True, "settled": None,
    }
    result = (await _run(run.id)).step_result
    assert (result["failures"], result["failing_total"], result["tests_passed"]) == (
        [NEW, {"name": "e2e/b.spec.ts:9", "kind": "base"}, FLAKY], 5, False)
    # a later report with passing tests clears them
    await _report(run)
    assert (await _wf(b.task_id)).finish_tests is None
    result = (await _run(run.id)).step_result
    assert (result["failures"], result["failing_total"]) == ([], None)


async def test_failures_validation(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    invalid = (422, "invalid_finish_result")
    too_large = (422, "too_large")
    assert await _code(_fail_report, run, [NEW], tests_passed=True) == invalid
    assert await _code(_fail_report, run, None, total=2, tests_passed=True) == invalid
    for failures in ([{"name": "t", "kind": "odd"}], [{"name": 3, "kind": "new"}], [{"name": "  ", "kind": "new"}],
                     [{"kind": "new"}], ["t"], {"name": "t", "kind": "new"}, "t"):
        assert await _code(_fail_report, run, failures) == invalid, failures
    for total in (0, -1, True, "3", 1.5):
        assert await _code(_fail_report, run, [NEW, BASE], total=total) == invalid, total
    assert await _code(_fail_report, run, [NEW] * 21) == too_large
    assert await _code(_fail_report, run, [{"name": "x" * 301, "kind": "new"}]) == too_large
    assert await _code(_test_failures, run, [NEW], "d" * 2001) == too_large
    assert await _code(_test_failures, run, []) == invalid
    assert await _code(_test_failures, run, None) == invalid
    for diagnosis in ("  ", "\x00", None, 3):
        assert await _code(_test_failures, run, [NEW], diagnosis) == invalid, diagnosis
    # nothing was stored; the limits themselves are accepted
    assert (await _wf(b.task_id)).finish_tests is None
    await _fail_report(run, [{"name": "x" * 300, "kind": "new"}] + [BASE] * 19, total=20)
    await _test_failures(run, [NEW], "d" * 2000)


async def test_report_test_failures_replaces_the_runs_result(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _fail_report(run, [BASE])
    await _test_failures(run, [NEW, FLAKY], total=4)
    assert (await _run(run.id)).step_result == {
        "test_failures": [NEW, FLAKY], "failing_total": 4, "diagnosis": "It fails because the layout overflows.",
    }
    await _test_failures(run, [BASE], " Only the mobile test. ")
    assert (await _run(run.id)).step_result == {
        "test_failures": [BASE], "failing_total": None, "diagnosis": "Only the mobile test.",
    }
    wf = await _wf(b.task_id)
    assert wf.finish_tests == {
        "failures": [BASE], "failing_total": None, "diagnosis": "Only the mobile test.", "delivered": False,
        "settled": None,
    }


async def test_the_known_failures_line_is_in_the_finish_prompt(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, run = await _to_finish(db, tc)
    assert "Known failing tests: tolerated" in run.prompt


async def test_the_setting_is_frozen_when_done_begins(db, tc_factory):
    from app.projects.models import Project
    from app.tasks.models import Task

    tc = tc_factory(lifespan=True)
    b, review = await _final_review(db, tc)
    _patch_project(tc, tolerate_known_test_failures=False)
    await _review(review, "approved")
    await _finish(b.manager.id, review, "completed")
    run = await _last(b.task_id)
    assert "Known failing tests: not tolerated" in run.prompt
    assert (await _wf(b.task_id)).finish_tolerates_known is False
    _patch_project(tc, tolerate_known_test_failures=True)
    wf = await _wf(b.task_id)
    async with SessionLocal() as s:
        project = await s.get(Project, (await s.get(Task, b.task_id)).project_id)
        assert project.tolerate_known_test_failures is True
        assert engine.tolerates_known(project, wf) is False


def test_a_row_from_before_falls_back_to_the_project():
    """A Done-stage row frozen before the setting existed follows the project's setting."""
    from app.projects.models import Project
    from app.workflow.models import Stage, TaskWorkflow

    project = Project(key="PAY", name="P", tolerate_known_test_failures=False)
    assert engine.tolerates_known(project, TaskWorkflow(stage=Stage.done, finish_tolerates_known=None)) is False
    assert engine.tolerates_known(project, TaskWorkflow(stage=Stage.done, finish_tolerates_known=True)) is True
    assert engine.tolerates_known(project, TaskWorkflow(stage=Stage.review, finish_tolerates_known=True)) is False


async def test_enter_done_clears_finish_tests(db, tc_factory):
    from app.workflow.models import TaskWorkflow

    tc = tc_factory(lifespan=True)
    b, review = await _final_review(db, tc)
    async with SessionLocal() as s:
        wf = await s.get(TaskWorkflow, b.task_id)
        wf.finish_tests = {"failures": [NEW], "failing_total": None, "diagnosis": None, "delivered": True,
                           "settled": None}
        await s.commit()
    await _review(review, "approved")
    await _finish(b.manager.id, review, "completed")
    wf = await _wf(b.task_id)
    assert (wf.stage, wf.finish_tests) == ("done", None)
