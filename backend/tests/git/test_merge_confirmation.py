"""An agent's merge that MegooColab can't confirm escalates `merge_not_confirmed` (the cause in the event), and a
later read that sees the merge still finishes the round."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.git import jobs, providers, service
from app.git.models import TaskPullRequest
from app.jobs.models import Job
from app.workflow.models import TaskWorkflow
from tests.git.test_agent_review import APPROVED, _agent_review, _end, _end_review
from tests.git.test_send_back import BRANCH, _kinds, _wf, _world

LASTING = ["forbidden", "unauthorized", "not_found", "bad_token", "url_mismatch"]


async def _confirming(client, db):
    """PAY-1, its agent review approved and merged: the round waits on `merge_confirmation`."""
    w, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    await _end_review(task, owner, APPROVED)
    assert (await _wf(task.id)).needs == "merge_confirmation"
    return task


def _status(state: str) -> providers.PrStatus:
    return providers.PrStatus(state=state, checks="none", review="none", merged_at=None, head_sha="a",
                              head_branch=BRANCH)


async def _read(task, monkeypatch, result) -> None:
    """One read of the main pull request: `result` is an error code it fails with, or the PR state it sees."""
    async def fetch(conn, ref):
        if result in ("open", "merged", "closed"):
            return _status(result)
        raise providers.GitProviderError(result)

    monkeypatch.setattr(providers, "fetch_pr", fetch)
    async with SessionLocal() as s:
        row = await s.get(TaskPullRequest, (task.id, "main"))
        await service.refresh_pr(s, row)
        await s.commit()


async def _cause(task_id) -> str | None:
    escalated = await _kinds(task_id, "workflow.escalated")
    assert escalated, "not escalated"
    return escalated[-1].data.get("cause")


async def _escalated(task_id, cause: str) -> None:
    wf = await _wf(task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "merge_not_confirmed")
    assert await _cause(task_id) == cause


async def _still_waiting(task_id) -> None:
    wf = await _wf(task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "merge_confirmation", None)


@pytest.mark.parametrize("code", LASTING)
async def test_a_lasting_error_escalates_on_the_first_failure(client, db, monkeypatch, code):
    task = await _confirming(client, db)
    await _read(task, monkeypatch, code)
    await _escalated(task.id, code)
    (escalated,) = await _kinds(task.id, "workflow.escalated")
    assert escalated.data == {"reason": "merge_not_confirmed", "cause": code}


async def test_a_passing_error_escalates_on_the_third_failure(client, db, monkeypatch):
    task = await _confirming(client, db)
    for _ in range(2):
        await _read(task, monkeypatch, "unreachable")
        await _still_waiting(task.id)
    await _read(task, monkeypatch, "unreachable")
    await _escalated(task.id, "unreachable")


async def test_the_poll_exception_path_counts(client, db, monkeypatch):
    task = await _confirming(client, db)

    async def boom(db, row):
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "refresh_pr", boom)
    for i in range(3):
        async with SessionLocal() as s:  # due now
            await s.execute(update(TaskPullRequest).where(TaskPullRequest.task_id == task.id).values(
                next_check_at=datetime.now(UTC) - timedelta(seconds=1)))
            await s.commit()
        async with SessionLocal() as s:
            await jobs.pr_poll(s, {})
        if i < 2:
            await _still_waiting(task.id)
    await _escalated(task.id, "error")


async def _waited(task_id, minutes: int) -> None:
    async with SessionLocal() as s:
        await s.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == task_id).values(
            waiting_since=datetime.now(UTC) - timedelta(minutes=minutes)))
        await s.commit()


async def test_still_open_after_ten_minutes_escalates(client, db, monkeypatch):
    task = await _confirming(client, db)
    await _waited(task.id, 9)
    await _read(task, monkeypatch, "open")
    await _still_waiting(task.id)
    await _waited(task.id, 11)
    await _read(task, monkeypatch, "open")
    await _escalated(task.id, "still_open")


async def test_old_failures_dont_count(client, db, monkeypatch):
    w, task, owner, _ = await _agent_review(client, db)
    await _end(task, owner, "finish", {"tests_passed": True})
    async with SessionLocal() as s:
        await s.execute(update(TaskPullRequest).where(TaskPullRequest.task_id == task.id).values(failures=28))
        await s.commit()
    await _end_review(task, owner, APPROVED)
    await _read(task, monkeypatch, "unreachable")
    await _still_waiting(task.id)


async def test_a_merged_read_finishes_the_escalated_round(client, db, monkeypatch):
    task = await _confirming(client, db)
    await _read(task, monkeypatch, "forbidden")
    await _escalated(task.id, "forbidden")
    await _read(task, monkeypatch, "merged")
    wf = await _wf(task.id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("finished", None, None)
    assert len(await _kinds(task.id, "pr.merged")) == 1


async def test_a_closed_read_on_the_escalated_round_escalates_pr_closed(client, db, monkeypatch):
    task = await _confirming(client, db)
    await _read(task, monkeypatch, "forbidden")
    await _read(task, monkeypatch, "closed")
    wf = await _wf(task.id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "pr_closed")


async def test_accept_finishes_it(client, db, monkeypatch):
    task = await _confirming(client, db)
    await _read(task, monkeypatch, "forbidden")
    r = await client.post("/api/tasks/PAY-1/workflow/escalation", json={"action": "accept"})
    assert r.status_code == 200, r.text
    wf = await _wf(task.id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("finished", None, None)
    assert len(await _kinds(task.id, "human_review.approved")) == 1


async def _runs(task_id) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.task_id == task_id))


async def test_retry_reads_again_and_runs_no_agent(client, db, monkeypatch):
    task = await _confirming(client, db)
    await _read(task, monkeypatch, "forbidden")
    async with SessionLocal() as s:  # the read queued when the review ended is done
        await s.execute(delete(Job).where(Job.kind == "git.pr_refresh"))
        await s.commit()
    runs = await _runs(task.id)
    before = datetime.now(UTC)
    r = await client.post("/api/tasks/PAY-1/workflow/escalation", json={"action": "retry"})
    assert r.status_code == 200, r.text
    wf = await _wf(task.id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "merge_confirmation", None)
    assert wf.waiting_since >= before
    async with SessionLocal() as s:
        assert (await s.execute(select(Job.id).where(Job.kind == "git.pr_refresh"))).first() is not None
        assert (await s.get(TaskPullRequest, (task.id, "main"))).failures == 0
    assert await _runs(task.id) == runs


async def test_human_review_mode_never_escalates_merge_not_confirmed(client, db, monkeypatch):
    _, _, task = await _world(client, db)
    await _read(task, monkeypatch, "forbidden")
    wf = await _wf(task.id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "human_code_review", None)
    assert await _kinds(task.id, "workflow.escalated") == []
