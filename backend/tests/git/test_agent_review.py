"""An agent reviews the task's pull request (piece 4): its review run, what it reports, and what follows."""

import pytest
from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent, AgentBinding
from app.core.db import SessionLocal
from app.git import providers, service
from app.git.models import TaskPullRequest
from app.jobs.models import Job
from app.projects.models import Project
from app.tasks.models import Task
from app.workflow import engine
from app.workflow.models import RunRole, TaskWorkflow
from tests.git.test_send_back import BRANCH, _fix_runs, _kinds, _owner, _wf, _world
from tests.workflow.test_engine import _finish


async def _review_runs(task_id) -> list[AgentRun]:
    async with SessionLocal() as s:
        return list((await s.execute(select(AgentRun).where(AgentRun.task_id == task_id,
                                                           AgentRun.workflow_role == "pr_review")
                                     .order_by(AgentRun.created_at))).scalars())


async def _agent(owner_id, name="review-bot") -> Agent:
    async with SessionLocal() as s:
        agent = Agent(owner_id=owner_id, name=name, program="claude_code")
        s.add(agent)
        await s.commit()
        return agent


async def test_review_prompt_names_the_pr_and_round_and_keeps_the_workflow_agent(client, db):
    w, _, task = await _world(client, db)
    other = await _agent(await _owner(task))
    async with SessionLocal() as s:
        wf = await s.get(TaskWorkflow, task.id)
        run = await engine.enqueue(s, wf, await s.get(Task, task.id), RunRole.pr_review,
                                   requested_by=await _owner(task), agent_id=other.id)
        await s.commit()
    assert run.agent_id == other.id and run.policy == "workspace"
    assert run.prompt.startswith("# Review: the pull request on the host")
    assert "## Pull request to review" in run.prompt
    assert f"Pull request: {w.pr_url} (branch {BRANCH}) · review round 1" in run.prompt
    assert (await _wf(task.id)).agent_id == task.assignee_agent_id  # the task's agent stays the workflow's


# -- the flow (Task 3) ------------------------------------------------------------------------------------------


async def _agent_review(client, db, *, reviewer_name: str | None = None, bound: bool = True):
    """PAY-1 at the end of its Finish run, its project reviewing pull requests by agent."""
    w, _, task = await _world(client, db)
    owner = await _owner(task)
    reviewer = None
    async with SessionLocal() as s:
        project = (await s.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
        project.pr_review = "agent"
        if reviewer_name:
            reviewer = Agent(owner_id=owner, name=reviewer_name, program="claude_code")
            s.add(reviewer)
            await s.flush()
            project.pr_reviewer_agent_id = reviewer.id
            if bound:
                s.add(AgentBinding(agent_id=reviewer.id, project_id=project.id, local_path="C:/work/pay"))
        await s.execute(update(TaskWorkflow).values(finish_pr_review="agent", status="running", needs=None))
        await s.commit()
    return w, task, owner, reviewer


async def _end(task, owner, role: str, result: dict | None) -> AgentRun:
    """A run of `role` that reported `result`, ending now (the runner's run_finished)."""
    async with SessionLocal() as s:
        run = AgentRun(task_id=task.id, agent_id=task.assignee_agent_id, requested_by=owner, policy="workspace",
                       prompt="p", status="running", workflow_role=role, stage="done", step_result=result)
        s.add(run)
        await s.commit()
    await _finish(owner, run)
    return run


async def _queued_review(task_id) -> AgentRun:
    runs = [r for r in await _review_runs(task_id) if r.status == RunStatus.queued]
    assert len(runs) == 1, runs
    return runs[0]


async def _end_review(task, owner, result: dict | None) -> None:
    """The queued review run reports `result` and ends."""
    run = await _queued_review(task.id)
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run.id).values(step_result=result))
        await s.commit()
    await _finish(owner, run)


async def _end_fix(task, owner) -> None:
    run = next(r for r in await _fix_runs(task.id) if r.status == RunStatus.queued)
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run.id).values(
            step_result={"summary": "Fixed", "tests_passed": True}))
        await s.commit()
    await _finish(owner, run)


APPROVED = {"verdict": "approved", "summary": "Looks good", "findings": [], "merged": True, "merge_error": None}
CHANGES = {"verdict": "changes_requested", "summary": "Retry needs a back-off", "merged": False, "merge_error": None,
           "findings": [{"severity": "important", "file": "src/a.py", "line": 88, "summary": "No back-off"}]}


async def test_finish_with_agent_review_starts_a_review_run(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    run = await _queued_review(task.id)
    assert run.agent_id == task.assignee_agent_id and run.policy == "workspace"
    wf = await _wf(task.id)
    assert (wf.status, wf.stage) == ("running", "done")


async def test_approved_and_merged_finishes_once_the_merge_is_seen(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, APPROVED)
    wf = await _wf(task.id)
    assert (wf.status, wf.needs) == ("waiting_human", "merge_confirmation")
    (reviewed,) = await _kinds(task.id, "pr.agent_reviewed")
    assert {k: reviewed.data[k] for k in ("verdict", "merged", "agent_name", "pr_number", "findings")} == {
        "verdict": "approved", "merged": True, "agent_name": "laptop-claude", "pr_number": 1, "findings": 0}
    async with SessionLocal() as s:  # MegooColab looks at the pull request again at once
        assert (await s.execute(select(Job.id).where(Job.kind == "git.pr_refresh"))).first() is not None
    async with SessionLocal() as s:
        merged = providers.PrStatus(state="merged", checks="success", review="none", merged_at=None, head_sha="a")
        await service.apply_status(s, task.id, "main", merged)
        await s.commit()
    assert (await _wf(task.id)).status == "finished"


# -- an agent's merge waits quietly for its confirmation ---------------------------------------------------------


async def _needs_you_refs(client) -> list[str]:
    r = await client.get("/api/dashboard")
    assert r.status_code == 200, r.text
    return [n["ref"] for n in r.json()["needs"]]


async def _needs_you_notices(task_id) -> list[str]:
    from app.notifications.models import Kind, Notification

    async with SessionLocal() as s:
        return list((await s.execute(select(Notification.title).where(
            Notification.task_id == task_id, Notification.kind == Kind.needs_you))).scalars())


async def test_an_agent_merge_rests_out_of_needs_you_without_a_notice(client, db):
    from datetime import UTC, datetime

    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    async with SessionLocal() as s:  # earlier failed reads don't count against the new wait
        await s.execute(update(TaskPullRequest).where(TaskPullRequest.task_id == task.id).values(failures=4))
        await s.commit()
    before = datetime.now(UTC)
    await _end_review(task, owner, APPROVED)
    assert (await _wf(task.id)).needs == "merge_confirmation"
    assert "PAY-1" not in await _needs_you_refs(client)
    assert (await client.get("/api/dashboard/count")).json() == {"needs_you": 0}
    board = await client.get("/api/projects/PAY/tasks", params={"needs_you": "true"})
    assert board.status_code == 200 and board.json() == []
    assert await _needs_you_notices(task.id) == []
    async with SessionLocal() as s:
        row = await s.get(TaskPullRequest, (task.id, "main"))
    assert row.failures == 0 and before <= row.next_check_at <= datetime.now(UTC)


async def test_a_person_taking_over_still_waits_on_code_review(client, db):
    from app.auth.models import User

    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, {**APPROVED, "merged": False, "merge_error": "Required review missing"})
    assert (await _wf(task.id)).escalation_reason == "agent_merge_failed"
    async with SessionLocal() as s:
        await engine.decide_escalation(s, await s.get(User, owner), await s.get(Task, task.id), "accept")
        await s.commit()
    assert (await _wf(task.id)).needs == "human_code_review"
    assert "PAY-1" in await _needs_you_refs(client)


async def _back_merge(task_id) -> None:
    async with SessionLocal() as s:
        await s.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == task_id).values(
            back_merge_branch="megoo/PAY-1-back", back_merge_pr_url="https://github.com/acme/pay/pull/2"))
        await s.commit()


async def _untracked(task_id) -> None:
    async with SessionLocal() as s:
        await s.execute(update(TaskPullRequest).where(TaskPullRequest.task_id == task_id).values(connection_id=None))
        await s.commit()


async def _other_branch(task_id) -> None:
    async with SessionLocal() as s:
        await s.execute(update(TaskPullRequest).where(TaskPullRequest.task_id == task_id).values(
            error="branch_mismatch"))
        await s.commit()


@pytest.mark.parametrize("change", [_back_merge, _untracked, _other_branch])
async def test_a_back_merge_pr_rests_on_code_review(client, db, change):
    """A person merges the back-merge pull request; an untracked or other-branch one is never confirmed alone."""
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await change(task.id)
    await _end_review(task, owner, APPROVED)
    wf = await _wf(task.id)
    assert (wf.status, wf.needs) == ("waiting_human", "human_code_review")


async def test_mark_merged_finishes_a_merge_confirmation(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, APPROVED)
    assert (await _wf(task.id)).needs == "merge_confirmation"
    r = await client.post("/api/tasks/PAY-1/workflow/human-review", json={"approved": True})
    assert r.status_code == 200, r.text
    assert (await _wf(task.id)).status == "finished"
    assert len(await _kinds(task.id, "human_review.approved")) == 1


async def test_a_changes_requested_webhook_during_merge_confirmation_is_ignored(client, db):
    from app.git import send_back

    w, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, APPROVED)
    trigger = send_back.Trigger(kind="review", pr_url=w.pr_url, pr_number=1, by="rev", excerpt="Two things",
                                where=None, association="COLLABORATOR", host="github")
    async with SessionLocal() as s:
        assert await send_back.consider(s, await s.get(Task, task.id), trigger) == "ignored:not_waiting"
        await s.commit()
    assert (await _wf(task.id)).needs == "merge_confirmation"


async def _bind_task_agent(task) -> None:
    async with SessionLocal() as s:  # as for any task's agent: bound to the project (resume checks it)
        project = (await s.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
        s.add(AgentBinding(agent_id=task.assignee_agent_id, project_id=project.id, local_path="C:/work/pay"))
        await s.commit()


async def test_resume_after_a_pause_rests_on_merge_confirmation(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, APPROVED)
    waited = (await _wf(task.id)).waiting_since
    await _bind_task_agent(task)
    assert (await client.post("/api/tasks/PAY-1/workflow/pause")).status_code == 200
    async with SessionLocal() as s:  # a read failed while paused
        await s.execute(update(TaskPullRequest).where(TaskPullRequest.task_id == task.id).values(failures=3))
        await s.commit()
    r = await client.post("/api/tasks/PAY-1/workflow/resume")
    assert r.status_code == 200, r.text
    wf = await _wf(task.id)
    assert (wf.status, wf.needs) == ("waiting_human", "merge_confirmation")
    assert wf.waiting_since > waited
    assert await _needs_you_notices(task.id) == []
    async with SessionLocal() as s:
        assert (await s.get(TaskPullRequest, (task.id, "main"))).failures == 0
    assert len([x for x in await _review_runs(task.id) if x.status == RunStatus.queued]) == 0


async def test_resume_finishes_a_merge_seen_while_paused(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, APPROVED)
    await _bind_task_agent(task)
    assert (await client.post("/api/tasks/PAY-1/workflow/pause")).status_code == 200
    async with SessionLocal() as s:  # seen while paused, so nothing settled then
        merged = providers.PrStatus(state="merged", checks="success", review="none", merged_at=None, head_sha="a")
        await service.apply_status(s, task.id, "main", merged)
        await s.commit()
    assert (await _wf(task.id)).status == "paused"
    assert (await client.post("/api/tasks/PAY-1/workflow/resume")).status_code == 200
    assert (await _wf(task.id)).status == "finished"


async def test_approved_but_not_merged_asks_a_person(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, {**APPROVED, "merged": False, "merge_error": "Required review missing"})
    wf = await _wf(task.id)
    assert (wf.needs, wf.escalation_reason) == ("escalation", "agent_merge_failed")
    (reviewed,) = await _kinds(task.id, "pr.agent_reviewed")
    assert reviewed.data["merge_error"] == "Required review missing"


async def test_changes_requested_sends_back_and_the_fix_is_reviewed_again(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, CHANGES)
    (sent,) = await _kinds(task.id, "pr.sent_back")
    assert (sent.data["kind"], sent.data["by"], sent.data["round"]) == ("agent_review", "laptop-claude", 1)
    assert sent.data["where"] == "src/a.py:88"
    await _end_fix(task, owner)
    again = await _queued_review(task.id)
    assert "review round 2" in again.prompt


async def test_the_agent_asks_for_changes_three_times_then_a_person_decides(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    for _ in range(3):
        await _end_review(task, owner, CHANGES)
        await _end_fix(task, owner)
    await _end_review(task, owner, CHANGES)
    wf = await _wf(task.id)
    assert (wf.needs, wf.escalation_reason) == ("escalation", "pr_fix_rounds_exhausted")
    assert len(await _fix_runs(task.id)) == 3


async def test_a_chosen_reviewer_runs_the_review_and_the_task_agent_fixes(client, db):
    _, task, owner, reviewer = await _agent_review(client, db, reviewer_name="review-bot")
    await _end(task, owner, "finish", {"tests_passed": True})
    assert (await _queued_review(task.id)).agent_id == reviewer.id
    assert (await _wf(task.id)).agent_id == task.assignee_agent_id
    await _end_review(task, owner, CHANGES)
    (fix,) = await _fix_runs(task.id)
    assert fix.agent_id == task.assignee_agent_id


async def test_a_failed_review_run_retries_with_the_same_reviewer(client, db):
    _, task, owner, reviewer = await _agent_review(client, db, reviewer_name="review-bot")
    await _end(task, owner, "finish", {"tests_passed": True})
    await _finish(owner, await _queued_review(task.id), "failed")
    assert (await _queued_review(task.id)).agent_id == reviewer.id


async def test_an_unbound_reviewer_escalates(client, db):
    _, task, owner, _ = await _agent_review(client, db, reviewer_name="review-bot", bound=False)
    await _end(task, owner, "finish", {"tests_passed": True})
    wf = await _wf(task.id)
    assert (wf.needs, wf.escalation_reason) == ("escalation", "agent_review_unavailable")
    assert await _review_runs(task.id) == []


async def test_a_merge_during_the_review_finishes_the_task(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    async with SessionLocal() as s:
        await s.execute(update(TaskPullRequest).where(TaskPullRequest.task_id == task.id).values(state="merged"))
        await s.commit()
    await _end_review(task, owner, CHANGES)
    assert (await _wf(task.id)).status == "finished"
    assert await _kinds(task.id, "pr.sent_back") == []


async def test_no_verdict_nudges_then_escalates(client, db):
    _, task, owner, reviewer = await _agent_review(client, db, reviewer_name="review-bot")
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, None)
    nudge = await _queued_review(task.id)
    assert nudge.agent_id == reviewer.id
    await _end_review(task, owner, None)
    wf = await _wf(task.id)
    assert (wf.needs, wf.escalation_reason) == ("escalation", "agent_review_incomplete")


async def test_human_review_is_unchanged(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    async with SessionLocal() as s:
        await s.execute(update(TaskWorkflow).values(finish_pr_review="human"))
        await s.commit()
    await _end(task, owner, "finish", {"tests_passed": True})
    wf = await _wf(task.id)
    assert (wf.status, wf.needs) == ("waiting_human", "human_code_review")
    assert await _review_runs(task.id) == []


# -- the final review's findings ---------------------------------------------------------------------------------


async def test_the_review_run_can_use_the_host_tools_but_must_not_change_the_repository(client, db):
    """The reviewer runs gh/glab/tea (refused by the read-only policy), so it runs in the workspace; a change to the
    repository is still caught as in a read-only stage."""
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    run = await _queued_review(task.id)
    assert run.policy == "workspace"
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run.id).values(
            step_result=CHANGES, git_before={"head": "a", "branch": "x", "dirty": False},
            git_after={"head": "b", "branch": "x", "dirty": False}))
        await s.commit()
    await _finish(owner, run)
    wf = await _wf(task.id)
    assert (wf.needs, wf.escalation_reason) == ("escalation", "enforcement_violation")


async def test_the_design_and_plan_reach_the_review_and_fix_runs(client, db):
    from app.agent_runs import service as runs

    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    run = await _queued_review(task.id)
    async with SessionLocal() as s:
        fields = await runs._v2_start_fields(s, await s.get(AgentRun, run.id), await s.get(Task, task.id), "PAY-1")
    assert "files" in fields  # .megoocolab/design.md and plan.md, as for every Build and Review role
    await _end_review(task, owner, CHANGES)
    (fix,) = await _fix_runs(task.id)
    async with SessionLocal() as s:
        fields = await runs._v2_start_fields(s, await s.get(AgentRun, fix.id), await s.get(Task, task.id), "PAY-1")
    assert "files" in fields


async def test_resume_after_a_pause_during_the_review_reviews_again(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _queued_review(task.id)
    async with SessionLocal() as s:  # as for any task's agent: bound to the project (resume checks it)
        project = (await s.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
        s.add(AgentBinding(agent_id=task.assignee_agent_id, project_id=project.id, local_path="C:/work/pay"))
        await s.commit()
    assert (await client.post("/api/tasks/PAY-1/workflow/pause")).status_code == 200
    async with SessionLocal() as s:  # the paused review run is over
        await s.execute(update(AgentRun).where(AgentRun.workflow_role == "pr_review").values(status="cancelled"))
        await s.commit()
    r = await client.post("/api/tasks/PAY-1/workflow/resume")
    assert r.status_code == 200, r.text
    wf = await _wf(task.id)
    assert (wf.status, wf.needs) == ("running", None)
    assert len([x for x in await _review_runs(task.id) if x.status == RunStatus.queued]) == 1


async def test_retry_when_the_reviewer_is_unavailable_starts_a_review(client, db):
    from app.auth.models import User

    _, task, owner, reviewer = await _agent_review(client, db, reviewer_name="review-bot", bound=False)
    await _end(task, owner, "finish", {"tests_passed": True})
    assert (await _wf(task.id)).escalation_reason == "agent_review_unavailable"
    async with SessionLocal() as s:  # the person binds the reviewer, then retries
        project = (await s.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
        s.add(AgentBinding(agent_id=reviewer.id, project_id=project.id, local_path="C:/work/pay"))
        await s.commit()
    async with SessionLocal() as s:
        await engine.decide_escalation(s, await s.get(User, owner), await s.get(Task, task.id), "retry")
        await s.commit()
    assert (await _queued_review(task.id)).agent_id == reviewer.id
    async with SessionLocal() as s:
        finishes = (await s.execute(select(AgentRun).where(AgentRun.task_id == task.id,
                                                           AgentRun.workflow_role == "finish"))).scalars().all()
    assert len(finishes) == 1  # no second Finish run


async def test_no_awaits_your_review_notice_while_an_agent_handles_the_pr(client, db):
    from app.notifications.models import Notification

    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, CHANGES)
    await _end_fix(task, owner)
    await _end_review(task, owner, APPROVED)
    async with SessionLocal() as s:
        titles = (await s.execute(select(Notification.title))).scalars().all()
    assert not [t for t in titles if "awaits your review" in t], titles


# ---- a merge refused for conflicts goes back to the task's agent ------------------------------------------------

CONFLICT = {**APPROVED, "merged": False, "merge_error": "Pull request has merge conflicts", "merge_blocked_by": "conflict"}


async def test_a_merge_refused_for_conflicts_sends_the_task_back(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, CONFLICT)
    wf = await _wf(task.id)
    assert wf.escalation_reason is None and wf.pr_fix_rounds == 1
    assert wf.pr_fix_trigger["kind"] == "merge_conflict"
    (fix,) = await _fix_runs(task.id)
    assert "## The pull request has merge conflicts" in fix.prompt
    assert "git merge" in fix.prompt and "never rebase" in fix.prompt.lower()
    assert "## Changes requested on the pull request" not in fix.prompt
    # the fix pushed: the reviewer reviews (and merges) again
    await _end_fix(task, owner)
    assert await _queued_review(task.id) is not None


async def test_other_refusals_still_come_to_a_person(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, {**CONFLICT, "merge_blocked_by": "protection",
                                    "merge_error": "Required review missing"})
    assert (await _wf(task.id)).escalation_reason == "agent_merge_failed"
    assert await _fix_runs(task.id) == []


async def test_conflict_rounds_share_the_send_back_limit(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    for _ in range(3):
        await _end_review(task, owner, CONFLICT)
        await _end_fix(task, owner)
    await _end_review(task, owner, CONFLICT)
    assert (await _wf(task.id)).escalation_reason == "pr_fix_rounds_exhausted"


async def test_review_report_keeps_what_blocked_the_merge(client, db):
    from app.git import agent_review

    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    run = await _queued_review(task.id)
    async with SessionLocal() as s:
        r = await s.get(AgentRun, run.id)
        await agent_review.report(s, r, "approved", "ok", [], False, "conflicts", merge_blocked_by="conflict")
        assert r.step_result["merge_blocked_by"] == "conflict"
        with pytest.raises(Exception):
            await agent_review.report(s, r, "approved", "ok", [], False, "x", merge_blocked_by="cosmic rays")
