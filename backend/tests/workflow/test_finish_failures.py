"""Finish runs report their failing tests (MC-97): report_finish's failures and report_test_failures."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.audit.models import AuditLog
from app.core.db import SessionLocal
from app.tasks.models import Task
from app.workflow import engine, finish
from tests.workflow.test_build import _last, _review
from tests.workflow.test_engine import _events, _finish, _runs, _wf
from tests.workflow.test_review_done import (
    PR_URL,
    _answer,
    _ask,
    _final_review,
    _patch_project,
    _report,
    _to_finish,
)

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


# ---- what the finish handler does with failing tests (step 6) ------------------------------------


async def _start_branch(task_id):
    async with SessionLocal() as s:
        return (await s.get(Task, task_id)).start_branch


async def _finish_runs(task_id) -> list[AgentRun]:
    return [r for r in await _runs(task_id) if r.workflow_role == "finish"]


async def _card(task_id, *, delivered: bool):
    wf = await _wf(task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "finish_tests_failed")
    assert (wf.finish_tests["delivered"], wf.finish_tests["settled"]) == (delivered, None)
    [ev] = await _events(task_id, "finish.tests_failed")
    assert ev.data["delivered"] is delivered and ev.actor_user_id is None
    return wf, ev


async def test_known_failures_finish_without_asking(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _fail_report(run, [BASE, FLAKY])
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("finished", None, None)
    assert wf.finish_tests["settled"] == "known"
    [ev] = await _events(b.task_id, "finish.known_failures")
    assert ev.data == {"failures": [BASE, FLAKY], "start_branch": await _start_branch(b.task_id)}
    assert await _events(b.task_id, "finish.tests_failed") == []
    assert len(await _finish_runs(b.task_id)) == 1


async def test_known_failures_wait_for_the_pr_when_review_is_required(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, review = await _final_review(db, tc)
    _patch_project(tc, pr_review="human")
    await _review(review, "approved")
    await _finish(b.manager.id, review, "completed")
    run = await _last(b.task_id)
    await _fail_report(run, [BASE])
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "human_code_review", None)
    assert wf.finish_tests["settled"] == "known"


async def test_setting_off_puts_known_failures_on_the_card(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, review = await _final_review(db, tc)
    _patch_project(tc, tolerate_known_test_failures=False)
    await _review(review, "approved")
    await _finish(b.manager.id, review, "completed")
    run = await _last(b.task_id)
    await _fail_report(run, [BASE, FLAKY])
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    _, ev = await _card(b.task_id, delivered=True)
    assert ev.data["failures"] == [BASE, FLAKY]
    assert await _events(b.task_id, "finish.known_failures") == []


async def test_incomplete_list_is_never_tolerated(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _fail_report(run, [BASE], total=25)
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    _, ev = await _card(b.task_id, delivered=True)
    assert (ev.data["failures"], ev.data["failing_total"]) == ([BASE], 25)


async def test_new_failure_delivered_escalates_at_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _fail_report(run, [NEW, BASE])
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    _, ev = await _card(b.task_id, delivered=True)
    assert ev.data == {"failures": [NEW, BASE], "failing_total": None, "delivered": True,
                       "start_branch": await _start_branch(b.task_id)}
    assert len(await _finish_runs(b.task_id)) == 1  # no nudge: it cannot change a delivered result
    assert (await _wf(b.task_id)).nudged is False


async def test_report_test_failures_escalates_not_delivered(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _test_failures(run, [NEW, FLAKY], total=3)
    await _finish(b.manager.id, run, "completed", session_id="sess-t")
    wf, ev = await _card(b.task_id, delivered=False)
    assert wf.finish_tests["diagnosis"] == "It fails because the layout overflows."
    assert (ev.data["failures"], ev.data["failing_total"]) == ([NEW, FLAKY], 3)
    assert len(await _finish_runs(b.task_id)) == 1


async def test_failing_report_without_names_escalates_card(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _report(run, tests_passed=False)
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    wf, ev = await _card(b.task_id, delivered=True)
    assert wf.finish_tests["failures"] == [] and ev.data["failures"] == []
    assert await _events(b.task_id, "finish.known_failures") == []


async def test_answered_question_counts_as_acceptance(db, tc_factory):
    """The task's "go ahead anyway": a person answered the finish session's question, so its delivery stands."""
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    qid = await _ask(b, run, "Two tests fail. Open the pull request anyway?")
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    assert (await _wf(b.task_id)).needs == "question"
    await _answer(b, qid, "go ahead anyway")
    resumed = await _last(b.task_id)
    assert (resumed.workflow_role, resumed.resume_session_ref) == ("finish", "sess-f")
    await _fail_report(resumed, [NEW])
    await _finish(b.manager.id, resumed, "completed", session_id="sess-f")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.escalation_reason) == ("finished", None)
    assert (wf.finish_tests["settled"], wf.finish_tests["accepted_by"], wf.finish_tests["accepted"]) == (
        "accepted", str(b.manager.id), [NEW["name"]])
    [ev] = await _events(b.task_id, "finish.failures_accepted")
    assert ev.actor_user_id == b.manager.id
    assert ev.data == {"failures": [NEW], "failing_total": None, "via": "answer"}
    async with SessionLocal() as s:
        [entry] = (await s.execute(
            select(AuditLog).where(AuditLog.action == "workflow.finish_failures_accepted"))).scalars().all()
        assert (entry.actor_user_id, entry.target_id) == (b.manager.id, b.task_id)
        assert entry.data["via"] == "answer" and entry.data["names"] == [NEW["name"]]
    assert await _events(b.task_id, "finish.tests_failed") == []


async def test_an_answer_in_another_session_does_not_count(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    qid = await _ask(b, run)
    await _finish(b.manager.id, run, "completed", session_id="sess-a")
    await _answer(b, qid)
    resumed = await _last(b.task_id)
    assert resumed.resume_session_ref == "sess-a"
    await _finish(b.manager.id, resumed, "completed", session_id="sess-a")  # no report: the nudge is fresh
    nudge = await _last(b.task_id)
    assert nudge.id != resumed.id and nudge.resume_session_ref is None
    await _fail_report(nudge, [NEW])
    await _finish(b.manager.id, nudge, "completed", session_id="sess-b")
    wf, _ = await _card(b.task_id, delivered=True)
    assert "accepted_by" not in wf.finish_tests
    assert await _events(b.task_id, "finish.failures_accepted") == []


async def test_no_report_still_nudges_then_finish_incomplete(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    nudge = await _last(b.task_id)
    assert nudge.id != run.id and nudge.workflow_role == "finish"
    assert nudge.prompt.rstrip().endswith(finish.FINISH_NUDGE)
    await _finish(b.manager.id, nudge, "completed", session_id="sess-f")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "finish_incomplete")
    assert wf.finish_tests is None
    assert await _events(b.task_id, "finish.tests_failed") == []


# ---- Finish anyway and Retry on the card (step 7) --------------------------------------------------


def _decide(tc, b, action):
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": action})
    assert r.status_code == 200, r.text
    return r.json()


async def _accepted_audit(task_id) -> list[AuditLog]:
    async with SessionLocal() as s:
        return list((await s.execute(select(AuditLog).where(
            AuditLog.action == "workflow.finish_failures_accepted", AuditLog.target_id == task_id))).scalars())


async def _not_delivered_card(db, tc, *, session_id="sess-t"):
    b, run = await _to_finish(db, tc)
    await _test_failures(run, [NEW])
    await _finish(b.manager.id, run, "completed", **({"session_id": session_id} if session_id else {}))
    await _card(b.task_id, delivered=False)
    return b, run


async def test_finish_anyway_after_a_delivery_finishes(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _fail_report(run, [NEW, BASE])
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    await _card(b.task_id, delivered=True)
    _decide(tc, b, "accept")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("finished", None, None)
    ft = wf.finish_tests
    assert (ft["accepted_by"], ft["accepted"], ft["settled"]) == (
        str(b.manager.id), [NEW["name"], BASE["name"]], "accepted")
    [ev] = await _events(b.task_id, "finish.failures_accepted")
    assert ev.actor_user_id == b.manager.id
    assert ev.data == {"failures": [NEW, BASE], "failing_total": None, "via": "card"}
    [entry] = await _accepted_audit(b.task_id)
    assert entry.actor_user_id == b.manager.id and entry.data["via"] == "card"
    assert len(await _finish_runs(b.task_id)) == 1


async def test_finish_anyway_with_required_review_waits_for_the_pr(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, review = await _final_review(db, tc)
    _patch_project(tc, pr_review="human")
    await _review(review, "approved")
    await _finish(b.manager.id, review, "completed")
    run = await _last(b.task_id)
    await _fail_report(run, [NEW])
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    _decide(tc, b, "accept")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "human_code_review", None)
    count = len(await _runs(b.task_id))
    assert tc.post(f"/api/tasks/{b.key}/workflow/pause").json()["status"] == "paused"
    r = tc.post(f"/api/tasks/{b.key}/workflow/resume")
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["needs"]) == ("waiting_human", "human_code_review")
    assert len(await _runs(b.task_id)) == count  # the settled finish does not run again


async def test_finish_anyway_not_delivered_resumes_the_session(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _not_delivered_card(db, tc)
    _decide(tc, b, "accept")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason, wf.nudged) == ("running", None, None, False)
    assert (wf.finish_tests["accepted"], wf.finish_tests["settled"]) == ([NEW["name"]], None)
    resumed = await _last(b.task_id)
    assert resumed.id != run.id and resumed.workflow_role == "finish"
    assert resumed.resume_session_ref == "sess-t"
    assert b.manager.name in resumed.resume_prompt
    assert '<untrusted source="accepted_tests">' in resumed.resume_prompt
    assert NEW["name"] in resumed.resume_prompt
    [ev] = await _events(b.task_id, "finish.failures_accepted")
    assert ev.data["via"] == "card"
    await _fail_report(resumed, [NEW])
    await _finish(b.manager.id, resumed, "completed", session_id="sess-t")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.escalation_reason) == ("finished", None)
    assert (wf.finish_tests["settled"], wf.finish_tests["accepted_by"]) == ("accepted", str(b.manager.id))
    assert len(await _events(b.task_id, "finish.failures_accepted")) == 1


async def test_a_test_outside_the_accepted_names_brings_the_card_back(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _not_delivered_card(db, tc)
    _decide(tc, b, "accept")
    resumed = await _last(b.task_id)
    other = {"name": "e2e/other.spec.ts:7", "kind": "new"}
    await _fail_report(resumed, [NEW, other])
    await _finish(b.manager.id, resumed, "completed", session_id="sess-t")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "finish_tests_failed")
    assert (wf.finish_tests["delivered"], wf.finish_tests["settled"]) == (True, None)
    assert "accepted_by" not in wf.finish_tests and "accepted" not in wf.finish_tests
    assert [e.data["failures"] for e in await _events(b.task_id, "finish.tests_failed")][-1] == [NEW, other]


async def test_finish_anyway_without_a_session_goes_into_a_fresh_prompt(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _not_delivered_card(db, tc, session_id=None)
    _decide(tc, b, "accept")
    resumed = await _last(b.task_id)
    assert (resumed.resume_session_ref, resumed.resume_prompt) == (None, None)
    head, _, tail = resumed.prompt.rpartition("\n\n## Failing tests accepted\n")
    assert head
    assert tail.startswith(f"{b.manager.name} chose Finish anyway")
    assert NEW["name"] in tail and tail.rstrip().endswith("the same failures.")


async def test_retry_clears_and_starts_a_fresh_finish(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _not_delivered_card(db, tc)
    _decide(tc, b, "retry")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason, wf.nudged) == ("running", None, None, False)
    assert wf.finish_tests is None
    fresh = await _last(b.task_id)
    assert fresh.id != run.id and fresh.workflow_role == "finish"
    assert (fresh.resume_session_ref, fresh.resume_prompt) == (None, None)
    assert await _events(b.task_id, "finish.failures_accepted") == []


def test_accept_handlers_include_finish_tests_failed():
    assert engine.ACCEPT_HANDLERS["finish_tests_failed"] is finish._accept_tests_failed
    assert engine.RETRY_HANDLERS["finish_tests_failed"] is finish._retry_tests_failed
