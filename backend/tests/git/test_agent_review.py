"""An agent reviews the task's pull request (piece 4): its review run, what it reports, and what follows."""

from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.agents.models import Agent
from app.core.db import SessionLocal
from app.tasks.models import Task
from app.workflow import engine
from app.workflow.models import RunRole, TaskWorkflow
from tests.git.test_send_back import BRANCH, _owner, _wf, _world


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
