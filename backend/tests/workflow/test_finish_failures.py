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
from tests.workflow.test_engine import SHA_A, SHA_B, _events, _finish, _runs, _wf
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
    assert engine.FIX_HANDLERS == {"finish_tests_failed": finish._fix_tests_failed}


# ---- Fix round on the card (MC-98) -----------------------------------------------------------------


async def _audit(task_id, action) -> list[AuditLog]:
    async with SessionLocal() as s:
        return list((await s.execute(select(AuditLog).where(
            AuditLog.action == action, AuditLog.target_id == task_id))).scalars())


async def _set_fix_rounds(task_id, n):
    from app.workflow.models import TaskWorkflow

    async with SessionLocal() as s:
        (await s.get(TaskWorkflow, task_id)).finish_fix_rounds = n
        await s.commit()


def _refused(tc, b, action="fix"):
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": action})
    assert r.status_code == 422, r.text
    return r.json()["detail"]


async def test_fix_round_starts_a_fresh_fix_run(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _not_delivered_card(db, tc)
    _decide(tc, b, "fix")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason, wf.stage) == ("running", None, None, "review")
    assert (wf.finish_fix_rounds, wf.review_round) == (1, 3)
    ft = wf.finish_tests
    assert (ft["fix_round"], ft["failures"], ft["diagnosis"]) == (
        1, [NEW], "It fails because the layout overflows.")
    assert not any(k.startswith("accepted") for k in ft)
    [decided] = await _events(b.task_id, "escalation.decided")
    assert decided.data == {"action": "fix", "reason": "finish_tests_failed"}
    [started] = await _events(b.task_id, "finish.fix_started")
    assert started.data == {"round": 1, "of": 2, "failures": [NEW], "failing_total": None}
    assert [e.data for e in await _events(b.task_id, "workflow.stage")][-1] == {"from": "done", "to": "review"}
    [entry] = await _audit(b.task_id, "workflow.fix")
    assert entry.actor_user_id == b.manager.id
    fix = await _last(b.task_id)
    assert fix.id != run.id and (fix.workflow_role, fix.resume_session_ref) == ("final_fix", None)
    assert fix.prompt.startswith("# Review: fix the tests that failed at finish")
    assert "## Tests that failed at finish" in fix.prompt and "Fix round 1 of 2" in fix.prompt
    assert '<untrusted source="finish_failures">' in fix.prompt
    assert NEW["name"] in fix.prompt and "It fails because the layout overflows." in fix.prompt
    assert "## Recorded test runs" in fix.prompt
    assert "## Review findings" not in fix.prompt


async def test_fix_is_refused_after_a_delivery(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _fail_report(run, [NEW])
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    await _card(b.task_id, delivered=True)
    assert _refused(tc, b) == "cannot_fix_here"
    assert await _events(b.task_id, "escalation.decided") == []
    assert await _audit(b.task_id, "workflow.fix") == []
    await _card(b.task_id, delivered=True)


async def test_fix_is_refused_for_another_reason(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    await _finish(b.manager.id, run, "completed", session_id="sess-f")
    await _finish(b.manager.id, await _last(b.task_id), "completed", session_id="sess-f")
    assert (await _wf(b.task_id)).escalation_reason == "finish_incomplete"
    assert _refused(tc, b) == "cannot_fix_here"
    assert await _events(b.task_id, "escalation.decided") == []


async def test_fix_rounds_are_limited(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _not_delivered_card(db, tc)
    await _set_fix_rounds(b.task_id, 2)
    assert _refused(tc, b) == "fix_rounds_exhausted"
    assert await _events(b.task_id, "escalation.decided") == []
    assert await _events(b.task_id, "finish.fix_started") == []
    assert await _audit(b.task_id, "workflow.fix") == []
    wf, _ = await _card(b.task_id, delivered=False)
    assert wf.finish_fix_rounds == 2 and "fix_round" not in wf.finish_tests


async def test_retry_keeps_the_fix_rounds(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _not_delivered_card(db, tc)
    await _set_fix_rounds(b.task_id, 1)
    _decide(tc, b, "retry")
    assert (await _wf(b.task_id)).finish_fix_rounds == 1


# ---- The fix run's end and the review of the fix (MC-98) --------------------------------------------

COMMITTED = {"git_before": {"head": SHA_A, "branch": "megoo/PAY-1", "dirty": False},
             "git_after": {"head": SHA_B, "branch": "megoo/PAY-1", "dirty": False, "uncommitted": False}}
NO_COMMIT = {"git_before": {"head": SHA_A, "branch": "megoo/PAY-1", "dirty": False},
             "git_after": {"head": SHA_A, "branch": "megoo/PAY-1", "dirty": False, "uncommitted": False}}
UNCOMMITTED = {"git_before": {"head": SHA_A, "branch": "megoo/PAY-1", "dirty": False},
               "git_after": {"head": SHA_A, "branch": "megoo/PAY-1", "dirty": True, "uncommitted": True}}


async def _fix_round(db, tc):
    """The not-delivered card, then Fix round: the fresh final_fix run."""
    b, _ = await _not_delivered_card(db, tc)
    _decide(tc, b, "fix")
    fix = await _last(b.task_id)
    assert fix.workflow_role == "final_fix"
    return b, fix


async def _fix_review(db, tc):
    """A fix round whose fix committed: the review of the fix."""
    b, fix = await _fix_round(db, tc)
    await _finish(b.manager.id, fix, "completed", **COMMITTED)
    review = await _last(b.task_id)
    assert review.workflow_role == "final_review"
    return b, review


def _no_filing(monkeypatch) -> list:
    filed = []

    async def record(db, task, review, *, summary, actor):
        filed.append(summary)

    monkeypatch.setattr("app.kb.filing.file_final_review", record)
    return filed


async def test_the_fix_is_reviewed(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, review = await _fix_review(db, tc)
    assert (review.resume_session_ref, review.policy) == (None, "read_only")
    assert review.prompt.startswith("# Review: review the fix for the tests that failed at finish")
    assert "## The fix to review" in review.prompt and "Fix round 1 of 2" in review.prompt
    assert f"git diff {SHA_A}..HEAD" in review.prompt
    assert NEW["name"] in review.prompt and "It fails because the layout overflows." in review.prompt
    assert "## Decisions the agent recorded" in review.prompt and "## Recorded test runs" in review.prompt
    assert "## Previous review findings" not in review.prompt
    assert "## Implementer's report" not in review.prompt
    wf = await _wf(b.task_id)
    assert (wf.finish_tests["fix_base"], wf.review_round, wf.stage) == (SHA_A, 3, "review")


async def test_an_approved_fix_runs_the_finish_again(db, tc_factory, monkeypatch):
    from app.workflow.models import StepReview

    filed = _no_filing(monkeypatch)
    tc = tc_factory(lifespan=True)
    b, review = await _fix_review(db, tc)
    await _review(review, "approved")
    await _finish(b.manager.id, review, "completed")
    wf = await _wf(b.task_id)
    assert (wf.stage, wf.status, wf.finish_tests, wf.finish_fix_rounds) == ("done", "running", None, 1)
    fresh = await _last(b.task_id)
    assert (fresh.workflow_role, fresh.resume_session_ref) == ("finish", None)
    assert len(await _finish_runs(b.task_id)) == 2
    result = [e for e in await _events(b.task_id, "review.result") if e.data["scope"] == "final"][-1]
    assert (result.data["round"], result.data["fix_round"], result.data["verdict"]) == (3, 1, "approved")
    async with SessionLocal() as s:
        row = (await s.execute(select(StepReview).where(StepReview.run_id == review.id))).scalar_one()
        assert (row.scope, row.round) == ("final", 3)
    # only the whole-branch review was filed: the task's "Final review" document stays that one
    assert filed == ["Final review round 1: approved"]


async def test_a_review_of_the_whole_branch_has_no_fix_round(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, review = await _final_review(db, tc)
    await _review(review, "approved")
    [result] = [e for e in await _events(b.task_id, "review.result") if e.data["scope"] == "final"]
    assert "fix_round" not in result.data


async def test_a_fix_with_findings_goes_to_a_person_and_accept_finishes_again(db, tc_factory):
    from tests.workflow.test_build import FINDING

    tc = tc_factory(lifespan=True)
    b, review = await _fix_review(db, tc)
    await _review(review, "changes_requested", [FINDING])
    await _finish(b.manager.id, review, "completed")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason, wf.stage) == (
        "waiting_human", "escalation", "finish_fix_not_clean", "review")
    assert (await _last(b.task_id)).id == review.id  # no second fix on its own
    _decide(tc, b, "accept")
    wf = await _wf(b.task_id)
    assert (wf.stage, wf.status, wf.escalation_reason, wf.finish_tests) == ("done", "running", None, None)
    fresh = await _last(b.task_id)
    assert (fresh.workflow_role, fresh.requested_by) == ("finish", b.manager.id)


async def test_a_fix_with_findings_retry_reviews_it_again(db, tc_factory):
    from tests.workflow.test_build import FINDING

    tc = tc_factory(lifespan=True)
    b, review = await _fix_review(db, tc)
    await _review(review, "changes_requested", [FINDING])
    await _finish(b.manager.id, review, "completed")
    _decide(tc, b, "retry")
    again = await _last(b.task_id)
    assert again.id != review.id and again.workflow_role == "final_review"
    assert again.prompt.startswith("# Review: review the fix for the tests that failed at finish")
    assert f"git diff {SHA_A}..HEAD" in again.prompt
    assert "## Previous review findings" not in again.prompt


async def test_a_review_of_the_fix_without_verdict_nudges_then_review_incomplete(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, review = await _fix_review(db, tc)
    await _finish(b.manager.id, review, "completed")
    nudge = await _last(b.task_id)
    assert nudge.id != review.id and nudge.workflow_role == "final_review"
    assert nudge.prompt.startswith("# Review: review the fix for the tests that failed at finish")
    await _finish(b.manager.id, nudge, "completed")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.escalation_reason) == ("waiting_human", "review_incomplete")


async def test_a_fix_without_a_commit_skips_the_review(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, fix = await _fix_round(db, tc)
    await _finish(b.manager.id, fix, "completed", **NO_COMMIT)
    [ev] = await _events(b.task_id, "finish.fix_no_commit")
    assert ev.data == {"round": 1}
    wf = await _wf(b.task_id)
    assert (wf.stage, wf.status, wf.finish_tests, wf.finish_fix_rounds) == ("done", "running", None, 1)
    fresh = await _last(b.task_id)
    assert (fresh.workflow_role, fresh.resume_session_ref) == ("finish", None)
    assert [r for r in await _runs(b.task_id) if r.workflow_role == "final_review" and r.created_at > fix.created_at] == []


async def test_unknown_git_state_still_reviews(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, fix = await _fix_round(db, tc)
    await _finish(b.manager.id, fix, "completed")
    review = await _last(b.task_id)
    assert review.workflow_role == "final_review"
    assert "find the commits made after the final review with `git log`" in review.prompt
    assert await _events(b.task_id, "finish.fix_no_commit") == []


async def test_an_uncommitted_fix_is_sent_back_first(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, fix = await _fix_round(db, tc)
    await _finish(b.manager.id, fix, "completed", session_id="fix-1", **UNCOMMITTED)
    commit = await _last(b.task_id)
    assert commit.workflow_role == "final_fix" and engine.is_commit_run(commit)
    assert await _events(b.task_id, "finish.fix_no_commit") == []
    await _finish(b.manager.id, commit, "completed", session_id="fix-1",
                  git_before={"head": SHA_A, "branch": "megoo/PAY-1", "dirty": True},
                  git_after={"head": SHA_B, "branch": "megoo/PAY-1", "dirty": False, "uncommitted": False})
    review = await _last(b.task_id)
    assert review.workflow_role == "final_review" and f"git diff {SHA_A}..HEAD" in review.prompt


async def test_a_second_round_and_no_third(db, tc_factory):
    sha_c = "c" * 40
    tc = tc_factory(lifespan=True)
    b, review = await _fix_review(db, tc)
    await _review(review, "approved")
    await _finish(b.manager.id, review, "completed")
    again = await _last(b.task_id)
    await _test_failures(again, [NEW])
    await _finish(b.manager.id, again, "completed", session_id="sess-2")
    assert (await _wf(b.task_id)).escalation_reason == "finish_tests_failed"
    _decide(tc, b, "fix")
    wf = await _wf(b.task_id)
    assert (wf.finish_fix_rounds, wf.review_round, wf.finish_tests["fix_round"]) == (2, 4, 2)
    assert "fix_base" not in wf.finish_tests
    fix2 = await _last(b.task_id)
    assert fix2.workflow_role == "final_fix" and "Fix round 2 of 2" in fix2.prompt
    await _finish(b.manager.id, fix2, "completed",
                  git_before={"head": SHA_B, "branch": "megoo/PAY-1", "dirty": False},
                  git_after={"head": sha_c, "branch": "megoo/PAY-1", "dirty": False, "uncommitted": False})
    review2 = await _last(b.task_id)
    assert review2.workflow_role == "final_review"
    assert "Fix round 2 of 2" in review2.prompt and f"git diff {SHA_B}..HEAD" in review2.prompt
    assert (await _wf(b.task_id)).finish_tests["fix_base"] == SHA_B
    await _review(review2, "approved")
    result = [e for e in await _events(b.task_id, "review.result") if e.data["scope"] == "final"][-1]
    assert (result.data["round"], result.data["fix_round"]) == (4, 2)
    await _finish(b.manager.id, review2, "completed")
    third = await _last(b.task_id)
    await _test_failures(third, [NEW])
    await _finish(b.manager.id, third, "completed", session_id="sess-3")
    assert (await _wf(b.task_id)).escalation_reason == "finish_tests_failed"
    assert _refused(tc, b) == "fix_rounds_exhausted"
    assert len(await _events(b.task_id, "finish.fix_started")) == 2


async def test_pause_and_resume_keep_the_rounds_text(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, fix = await _fix_round(db, tc)
    assert tc.post(f"/api/tasks/{b.key}/workflow/pause").json()["status"] == "paused"
    r = tc.post(f"/api/tasks/{b.key}/workflow/resume")
    assert r.status_code == 200, r.text
    again = await _last(b.task_id)
    assert again.id != fix.id and again.workflow_role == "final_fix"
    assert again.prompt.startswith("# Review: fix the tests that failed at finish")
    assert "## Tests that failed at finish" in again.prompt
    await _finish(b.manager.id, again, "completed", **COMMITTED)
    review = await _last(b.task_id)
    assert review.workflow_role == "final_review"
    assert tc.post(f"/api/tasks/{b.key}/workflow/pause").json()["status"] == "paused"
    r = tc.post(f"/api/tasks/{b.key}/workflow/resume")
    assert r.status_code == 200, r.text
    review_again = await _last(b.task_id)
    assert review_again.id != review.id and review_again.workflow_role == "final_review"
    assert review_again.prompt.startswith("# Review: review the fix for the tests that failed at finish")
    assert f"git diff {SHA_A}..HEAD" in review_again.prompt


# ---- The workflow API (step 8) ---------------------------------------------------------------------


async def test_workflow_api_returns_finish_tests(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish(db, tc)
    assert tc.get(f"/api/tasks/{b.key}/workflow").json()["finish_tests"] is None
    await _test_failures(run, [NEW, FLAKY], total=3)
    await _finish(b.manager.id, run, "completed", session_id="sess-t")
    assert tc.get(f"/api/tasks/{b.key}/workflow").json()["finish_tests"] == {
        "failures": [NEW, FLAKY], "failing_total": 3, "diagnosis": "It fails because the layout overflows.",
        "delivered": False, "settled": None, "accepted_by": None,
    }
    _decide(tc, b, "accept")
    await _fail_report(await _last(b.task_id), [NEW])
    await _finish(b.manager.id, await _last(b.task_id), "completed", session_id="sess-t")
    ft = tc.get(f"/api/tasks/{b.key}/workflow").json()["finish_tests"]
    assert (ft["failures"], ft["delivered"], ft["settled"], ft["accepted_by"]) == (
        [NEW], True, "accepted", b.manager.name)
