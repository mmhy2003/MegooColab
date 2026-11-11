"""Work left uncommitted never reaches a review: a run that may change the repository and ends with uncommitted changes
goes back to its agent to commit them (once), then a human decides. A read-only run is blamed only for what it changed
itself, and retrying a review that started on uncommitted work sends that work back to be committed first."""

import pytest
from sqlalchemy import update

from app.core.db import SessionLocal
from app.workflow.models import TaskWorkflow
from tests.workflow.test_build import FINDING, _building, _complete, _git, _last, _review
from tests.workflow.test_engine import SHA_A, SHA_B, _events, _finish, _started, _submit, _wf
from tests.workflow.test_review_done import _final_review

DIRTY = {"git_before": {"head": SHA_A, "branch": "megoo/PAY-1", "dirty": False},
         "git_after": {"head": SHA_A, "branch": "megoo/PAY-1", "dirty": True}}
STILL_DIRTY = {"git_before": {"head": SHA_A, "branch": "megoo/PAY-1", "dirty": True},
               "git_after": {"head": SHA_A, "branch": "megoo/PAY-1", "dirty": True}}
COMMITTED = {"git_before": {"head": SHA_A, "branch": "megoo/PAY-1", "dirty": True},
             "git_after": {"head": SHA_B, "branch": "megoo/PAY-1", "dirty": False}}
MARK = "You left changes in the worktree uncommitted"


async def _fix_round(db, tc):
    b, review = await _final_review(db, tc)
    await _review(review, "changes_requested", [FINDING])
    await _finish(b.manager.id, review, "completed")
    fix = await _last(b.task_id)
    assert fix.workflow_role == "final_fix"
    return b, fix


def _commit_text(run) -> str:
    return (run.resume_prompt or "") + run.prompt


async def test_a_fix_round_left_uncommitted_commits_before_the_re_review(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, fix = await _fix_round(db, tc)
    await _finish(b.manager.id, fix, "completed", session_id="fix-1", **DIRTY)
    commit = await _last(b.task_id)
    assert (commit.workflow_role, commit.policy, commit.resume_session_ref) == ("final_fix", "workspace", "fix-1")
    assert MARK in commit.resume_prompt  # the same session, told only to commit
    [event] = await _events(b.task_id, "workflow.uncommitted")
    assert event.data == {"role": "final_fix", "step": None}
    await _finish(b.manager.id, commit, "completed", session_id="fix-1", **COMMITTED)
    rereview = await _last(b.task_id)
    assert rereview.workflow_role == "final_review"
    assert (await _wf(b.task_id)).review_round == 2  # the commit run used no review round


async def test_still_uncommitted_asks_a_human_and_retry_sends_it_back_to_commit(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, fix = await _fix_round(db, tc)
    await _finish(b.manager.id, fix, "completed", session_id="fix-1", **DIRTY)
    commit = await _last(b.task_id)
    await _finish(b.manager.id, commit, "completed", session_id="fix-1", **STILL_DIRTY)
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "uncommitted_changes")
    assert wf.enforcement != "partially_enforced"  # a work run may change files: it just didn't commit them
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "retry"})
    assert r.status_code == 200, r.text
    again = await _last(b.task_id)
    assert again.id != commit.id and again.workflow_role == "final_fix" and MARK in _commit_text(again)
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "accept"})
    assert r.status_code == 409  # nothing to accept: it isn't waiting on an escalation any more


async def test_a_step_left_uncommitted_commits_before_its_review(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _building(db, tc)
    await _complete(run)
    await _finish(b.manager.id, run, "completed", session_id="impl-1", **DIRTY)
    commit = await _last(b.task_id)
    assert (commit.workflow_role, commit.step, commit.resume_session_ref) == ("implement", 1, "impl-1")
    assert MARK in commit.resume_prompt
    assert (await _wf(b.task_id)).review_round == 0
    await _finish(b.manager.id, commit, "completed", session_id="impl-1", **COMMITTED)  # no complete_step: it committed
    review = await _last(b.task_id)
    assert (review.workflow_role, review.step) == ("step_review", 1)
    assert (await _wf(b.task_id)).review_round == 1


async def test_a_clean_step_goes_straight_to_review(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _building(db, tc)
    await _complete(run)
    await _finish(b.manager.id, run, "completed", session_id="impl-1", **_git(SHA_A, SHA_B))
    assert (await _last(b.task_id)).workflow_role == "step_review"
    assert await _events(b.task_id, "workflow.uncommitted") == []


async def test_a_read_only_run_that_started_on_uncommitted_work_is_not_blamed_for_it(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _submit(b.task_id, run.id, "design")
    await _finish(b.manager.id, run, "completed", **STILL_DIRTY)
    wf = await _wf(b.task_id)
    assert wf.enforcement != "partially_enforced" and wf.escalation_reason is None
    assert (wf.status, wf.needs) == ("waiting_human", "design_approval")


@pytest.mark.parametrize("reason", ["final_review_not_clean", "enforcement_violation"])
async def test_retrying_a_review_stuck_on_uncommitted_work_commits_it_first(db, tc_factory, reason):
    """MF-79: the fix round left its work uncommitted, the read-only re-review couldn't approve it, and the workflow
    escalated. Retry sends the work back to be committed, then reviews it again."""
    tc = tc_factory(lifespan=True)
    b, fix = await _fix_round(db, tc)
    await _finish(b.manager.id, fix, "completed", session_id="fix-1", **_git(SHA_A, SHA_B))
    rereview = await _last(b.task_id)
    await _review(rereview, "changes_requested", [FINDING])
    await _finish(b.manager.id, rereview, "completed", **STILL_DIRTY)
    assert (await _wf(b.task_id)).escalation_reason == "final_review_not_clean"
    if reason == "enforcement_violation":  # how a task stuck before this release was escalated
        async with SessionLocal() as s:
            await s.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == b.task_id)
                            .values(escalation_reason=reason))
            await s.commit()
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "retry"})
    assert r.status_code == 200, r.text
    commit = await _last(b.task_id)
    assert commit.workflow_role == "final_fix" and MARK in _commit_text(commit)
    await _finish(b.manager.id, commit, "completed", **COMMITTED)
    again = await _last(b.task_id)
    assert again.workflow_role == "final_review" and (await _wf(b.task_id)).review_round == 2
