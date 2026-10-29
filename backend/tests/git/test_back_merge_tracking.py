"""A production fix's second pull request (Branch from): tracked beside the main one; the task waits for both."""

from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.git import service
from app.git.models import PR_BACK_MERGE, PR_MAIN, TaskPullRequest
from app.jobs.models import Job
from app.tasks.models import Task
from app.workflow.models import TaskWorkflow
from tests.git.test_tracking import BASE, PR, _finished_waiting, _refresh, github  # noqa: F401 — fixture
from tests.workflow.test_engine import _events, _wf

BACK = f"{BASE}/acme/pay/pull/8"
BACK_BRANCH = "megoo/PAY-1-to-develop"


async def _with_back_merge(db, tc, github, *, back_state="open", back_merged=False, back_ref=BACK_BRANCH,  # noqa: F811
                           back_url=BACK):
    """Waiting on the main PR (review on); then the back-merge PR is reported and tracked too."""
    b, _conn = await _finished_waiting(db, tc, github)
    github.set(number=8, state=back_state, merged=back_merged, ref=back_ref)
    async with SessionLocal() as s:
        await s.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == b.task_id)
                        .values(back_merge_pr_url=back_url, back_merge_branch=BACK_BRANCH))
        await s.execute(update(Task).where(Task.id == b.task_id).values(start_branch="main", back_merge_into="develop"))
        await service.track_pr(s, await s.get(Task, b.task_id), back_url, kind=PR_BACK_MERGE)
        await s.commit()
    return b


async def _rows(task_id) -> dict[str, TaskPullRequest]:
    async with SessionLocal() as s:
        rows = await s.execute(select(TaskPullRequest).where(TaskPullRequest.task_id == task_id))
        return {r.kind: r for r in rows.scalars()}


async def test_both_prs_merged_finishes(db, tc_factory, github):  # noqa: F811
    tc = tc_factory(lifespan=True)
    b = await _with_back_merge(db, tc, github)
    github.set(state="closed", merged=True)  # the main PR (#7)
    await _refresh(b.task_id)
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "human_code_review")  # the back-merge is still open
    github.set(number=8, state="closed", merged=True, ref=BACK_BRANCH)
    await _refresh(b.task_id)
    assert (await _wf(b.task_id)).status == "finished"
    assert sorted(e.data["url"] for e in await _events(b.task_id, "pr.merged")) == [PR, BACK]


async def test_back_merge_closed_escalates_even_if_main_merged(db, tc_factory, github):  # noqa: F811
    tc = tc_factory(lifespan=True)
    b = await _with_back_merge(db, tc, github)
    github.set(state="closed", merged=True)
    github.set(number=8, state="closed", merged=False, ref=BACK_BRANCH)
    await _refresh(b.task_id)
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "back_merge_pr_closed")
    [closed] = await _events(b.task_id, "pr.closed")
    assert closed.data == {"url": BACK, "kind": "back_merge"}


async def test_back_merge_closed_can_be_accepted(db, tc_factory, github):  # noqa: F811
    tc = tc_factory(lifespan=True)
    b = await _with_back_merge(db, tc, github)
    github.set(number=8, state="closed", merged=False, ref=BACK_BRANCH)
    await _refresh(b.task_id)
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "accept"})
    assert r.status_code == 200, r.text
    assert (await _wf(b.task_id)).status == "finished"


async def test_untracked_back_merge_waits_for_a_person(db, tc_factory, github):  # noqa: F811
    """The back-merge PR is on a host no connection covers: the merged main PR alone never finishes the task, but a
    closed main PR still escalates."""
    tc = tc_factory(lifespan=True)
    b = await _with_back_merge(db, tc, github, back_url="https://elsewhere.example/acme/pay/pull/8")
    rows = await _rows(b.task_id)
    assert rows[PR_MAIN].connection_id is not None and rows[PR_BACK_MERGE].connection_id is None
    github.set(state="closed", merged=True)
    await _refresh(b.task_id)
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "human_code_review")
    assert await _events(b.task_id, "pr.merged") == []


async def test_untracked_back_merge_does_not_hide_a_closed_main_pr(db, tc_factory, github):  # noqa: F811
    tc = tc_factory(lifespan=True)
    b = await _with_back_merge(db, tc, github, back_url="https://elsewhere.example/acme/pay/pull/8")
    github.set(state="closed", merged=False)
    await _refresh(b.task_id)
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "pr_closed")


async def test_back_merge_branch_mismatch_waits(db, tc_factory, github):  # noqa: F811
    tc = tc_factory(lifespan=True)
    b = await _with_back_merge(db, tc, github, back_ref="megoo/other")
    github.set(state="closed", merged=True)
    github.set(number=8, state="closed", merged=True, ref="megoo/other")
    await _refresh(b.task_id)
    rows = await _rows(b.task_id)
    assert rows[PR_BACK_MERGE].error == "branch_mismatch" and rows[PR_MAIN].error is None
    assert (await _wf(b.task_id)).status == "waiting_human"


async def test_refresh_job_reads_both_rows(db, tc_factory, github):  # noqa: F811
    tc = tc_factory(lifespan=True)
    b = await _with_back_merge(db, tc, github)
    github.set(state="open", runs=[("completed", "success")])
    github.set(number=8, state="closed", merged=False, ref=BACK_BRANCH)
    await _refresh(b.task_id)
    rows = await _rows(b.task_id)
    assert rows[PR_MAIN].checks == "success" and rows[PR_BACK_MERGE].state == "closed"
    queued = (await db.execute(select(Job.dedupe_key).where(Job.kind == "git.pr_refresh"))).scalars().all()
    assert set(queued) == {f"git.pr_refresh:{b.task_id}"}  # one job per task, whatever its rows


async def test_task_and_workflow_out_show_both_prs(db, tc_factory, github):  # noqa: F811
    tc = tc_factory(lifespan=True)
    b = await _with_back_merge(db, tc, github)
    await _refresh(b.task_id)
    task = tc.get(f"/api/tasks/{b.key}").json()
    assert task["pull_request"]["url"] == PR and task["back_merge_pull_request"]["url"] == BACK
    wf = tc.get(f"/api/tasks/{b.key}/workflow").json()
    assert wf["back_merge_pull_request"]["url"] == BACK and wf["back_merge_pr_url"] == BACK
    assert (wf["back_merge_branch"], wf["start_branch"], wf["back_merge_into"]) == (BACK_BRANCH, "main", "develop")
    assert wf["finish_outcome"] == "pr_opened" and wf["branch_from"] is None


async def test_webhook_refreshes_back_merge_row(db, tc_factory, github):  # noqa: F811
    tc = tc_factory(lifespan=True)
    b = await _with_back_merge(db, tc, github)
    async with SessionLocal() as s:
        conn_id = (await _rows(b.task_id))[PR_BACK_MERGE].connection_id
        from app.git.models import GitConnection

        conn = await s.get(GitConnection, conn_id)
        assert await service.rows_for_delivery(s, conn, "acme/pay", 8, None) == [b.task_id]
