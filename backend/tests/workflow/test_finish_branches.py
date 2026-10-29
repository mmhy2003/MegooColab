"""Branch from at the finish: the agent is told where to deliver, reports the back-merge, and a production fix in
pull-request mode waits for both pull requests."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.git.models import TaskPullRequest
from app.mcp_server import workflow_tools
from app.tasks.models import Task
from app.workflow import finish
from app.workflow.methodology import DEFAULTS_DIR
from app.workflow.models import Driver, TaskWorkflow, WorkflowStatus
from tests.workflow.test_build import _last, _review
from tests.workflow.test_engine import _finish, _wf
from tests.workflow.test_review_done import PR_URL, _final_review, _patch_project

BACK_URL = "https://github.com/acme/pay/pull/8"


async def _set_branches(task_id, start, back):
    async with SessionLocal() as s:
        await s.execute(update(Task).where(Task.id == task_id).values(start_branch=start, back_merge_into=back))
        await s.commit()


async def _finish_run(db, tc, start="main", back="develop", option=None):
    """The finish run queued for a task whose branch started from `start` (back-merge into `back`)."""
    b, review = await _final_review(db, tc)
    if option:
        _patch_project(tc, finishing_option=option)
    await _set_branches(b.task_id, start, back)
    await _review(review, "approved")
    await _finish(b.manager.id, review, "completed")
    run = await _last(b.task_id)
    assert run.workflow_role == "finish"
    return b, run


async def _report(run, outcome="pr_opened", pr_url=PR_URL, **kw):
    async with SessionLocal() as s:
        await finish.report_finish(s, await s.get(AgentRun, run.id), outcome, "megoo/PAY-1", pr_url, True, **kw)
        await s.commit()


async def _code(run, *args, **kw):
    with pytest.raises(HTTPException) as e:
        await _report(run, *args, **kw)
    return e.value.detail


async def test_finish_prompt_names_start_and_back_merge(db, tc_factory):
    _b, run = await _finish_run(db, tc_factory(lifespan=True))
    assert "Start branch: main\nBack-merge into: develop" in run.prompt


async def test_finish_prompt_without_back_merge(db, tc_factory):
    _b, run = await _finish_run(db, tc_factory(lifespan=True), start="develop", back=None)
    # (the methodology text mentions a "Back-merge into" branch; the Finishing section names none)
    assert "Start branch: develop" in run.prompt and "Back-merge into: " not in run.prompt


async def test_finish_prompt_with_unknown_start(db, tc_factory):
    _b, run = await _finish_run(db, tc_factory(lifespan=True), start=None, back=None)
    assert ("Start branch: unknown — deliver into the branch the task branch was created from (git merge-base helps)"
            in run.prompt)


async def test_report_finish_back_merge_rules(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _b, run = await _finish_run(db, tc)
    assert await _code(run) == "back_merge_required"
    assert await _code(run, back_merge_branch="megoo/PAY-1-to-develop") == "back_merge_pr_url_required"
    assert await _code(run, back_merge_branch="megoo/PAY-1-to-develop", back_merge_pr_url="ftp://x") == "invalid_pr_url"
    await _report(run, back_merge_branch="megoo/PAY-1-to-develop", back_merge_pr_url=BACK_URL)
    wf = await _wf(run.task_id)
    assert (wf.back_merge_branch, wf.back_merge_pr_url) == ("megoo/PAY-1-to-develop", BACK_URL)
    kinds = (await db.execute(select(TaskPullRequest.kind).where(TaskPullRequest.task_id == run.task_id))).scalars()
    assert sorted(kinds) == ["back_merge", "main"]


async def test_report_finish_back_merge_not_expected(db, tc_factory):
    _b, run = await _finish_run(db, tc_factory(lifespan=True), start="develop", back=None)
    assert await _code(run, back_merge_branch="megoo/x") == "back_merge_not_expected"


async def test_keep_branch_with_back_merge_takes_no_back_merge(db, tc_factory):
    _b, run = await _finish_run(db, tc_factory(lifespan=True), option="keep_branch")
    await _report(run, outcome="branch_kept", pr_url=None)
    assert await _code(run, outcome="branch_kept", pr_url=None, back_merge_branch="megoo/x") == "back_merge_not_expected"


async def test_production_fix_waits_for_both_prs_without_human_review(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _finish_run(db, tc)
    await _report(run, back_merge_branch="megoo/PAY-1-to-develop", back_merge_pr_url=BACK_URL)
    await _finish(b.manager.id, run, "completed")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "human_code_review")


async def test_normal_fix_without_human_review_finishes_on_report(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _finish_run(db, tc, start="develop", back=None)
    await _report(run)
    await _finish(b.manager.id, run, "completed")
    assert (await _wf(b.task_id)).status == "finished"


async def test_merge_local_with_back_merge_finishes_on_report(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _finish_run(db, tc, option="merge_local")
    await _report(run, outcome="merged_local", pr_url=None, back_merge_branch="develop")
    await _finish(b.manager.id, run, "completed")
    assert (await _wf(b.task_id)).status == "finished"


async def test_get_workflow_reports_branches(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run = await _finish_run(db, tc)
    async with SessionLocal() as s:
        task = await s.get(Task, b.task_id)
        view = await workflow_tools._workflow_view(s, task, await s.get(TaskWorkflow, b.task_id))
        assert view["branches"] == {"start": "main", "back_merge_into": "develop"}
    # a connect-only task: nothing recorded, so Branch from and the single repository's default
    plain = tc.post("/api/projects/PAY/tasks", json={"title": "Hotfix", "branch_from": "main"}).json()
    r = tc.post("/api/projects/PAY/repositories",
                json={"name": "pay", "url": "https://github.com/acme/pay", "provider": "github",
                      "default_branch": "develop"})
    assert r.status_code == 201, r.text
    async with SessionLocal() as s:
        task = await s.get(Task, __import__("uuid").UUID(plain["id"]))
        wf = TaskWorkflow(task_id=task.id, driver=Driver.connect_only, status=WorkflowStatus.running)
        s.add(wf)
        await s.flush()
        view = await workflow_tools._workflow_view(s, task, wf)
        assert view["branches"] == {"start": "main", "back_merge_into": "develop"}
        await s.rollback()


def test_finish_text_back_merge_section():
    text = (DEFAULTS_DIR / "finish.md").read_text(encoding="utf-8")
    section = text[text.index("## Back-merge"):]
    assert "Back-merge into" in text and "-to-" in section and "record_decision" in section
    assert "unless the task says otherwise" not in text
