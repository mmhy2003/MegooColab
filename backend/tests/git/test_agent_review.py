"""An agent reviews the task's pull request (piece 4): its review run, what it reports, and what follows."""

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
    assert run.agent_id == other.id and run.policy == "read_only"
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
    assert run.agent_id == task.assignee_agent_id and run.policy == "read_only"
    wf = await _wf(task.id)
    assert (wf.status, wf.stage) == ("running", "done")


async def test_approved_and_merged_finishes_once_the_merge_is_seen(client, db):
    _, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, APPROVED)
    wf = await _wf(task.id)
    assert (wf.status, wf.needs) == ("waiting_human", "human_code_review")
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
