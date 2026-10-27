"""Pull-request tracking (GIT-3/4/5) and the Done stage (WF-6a): a merge in the git host finishes the task."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.audit.models import AuditLog
from app.core.crypto import encrypt
from app.core.db import SessionLocal
from app.git import jobs, providers, service
from app.git.models import GitConnection, TaskPullRequest
from app.jobs.models import Job
from app.workflow import finish
from app.workflow.methodology import DEFAULTS_DIR
from tests.workflow.test_build import _last, _review
from tests.workflow.test_engine import _events, _finish, _runs, _wf
from tests.workflow.test_review_done import (
    _final_review,
    _patch_project,
    _report,
    _to_finish,
)

BASE = "https://git.acme.io"
PR = f"{BASE}/acme/pay/pull/7"


class FakeGitHub:
    """A GitHub Enterprise API at git.acme.io/api/v3 with one mutable pull request per repository."""

    def __init__(self) -> None:
        self.prs: dict[tuple[str, int], dict] = {}
        self.fail: int | Exception | None = None
        self.calls = 0

    def set(self, path="acme/pay", number=7, state="open", merged=False, runs=()):
        self.prs[(path, number)] = {"state": state, "merged": merged, "runs": list(runs)}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if isinstance(self.fail, Exception):
            raise self.fail
        if isinstance(self.fail, int):
            return httpx.Response(self.fail, json={"message": "x"})
        if self.fail == "garbage":
            return httpx.Response(200, text="<html>")
        parts = request.url.path.removeprefix("/api/v3/repos/").split("/")
        key = ("/".join(parts[:2]), None)
        rest = parts[2:]
        if rest[:1] == ["pulls"]:
            pr = self.prs.get((key[0], int(rest[1])))
            if pr is None:
                return httpx.Response(404, json={"message": "Not Found"})
            if rest[2:] == ["reviews"]:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json={"state": pr["state"], "merged": pr["merged"],
                                             "merged_at": "2026-10-27T10:00:00Z" if pr["merged"] else None,
                                             "head": {"sha": "abc123"}})
        if rest[:1] == ["commits"]:
            runs = next((p["runs"] for (path, _n), p in self.prs.items() if path == key[0]), [])
            if rest[2:] == ["status"]:
                return httpx.Response(200, json={"state": "pending", "total_count": 0})
            return httpx.Response(200, json={"check_runs": [{"status": s, "conclusion": c} for s, c in runs]})
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def github(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(providers, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    return fake


async def _connection(db, name="GHE", base=BASE, secret="hook-secret") -> GitConnection:
    conn = GitConnection(name=name, kind="github", base_url=base, token_enc=encrypt("tok"),
                         webhook_secret_enc=encrypt(secret) if secret else None)
    db.add(conn)
    await db.commit()
    return conn


def _link(tc, conn, url=f"{BASE}/acme/pay", name="pay", provider="github"):
    r = tc.post("/api/projects/PAY/repositories",
                json={"name": name, "url": url, "provider": provider, "connection_id": str(conn.id) if conn else None})
    assert r.status_code == 201, r.text
    return r.json()


async def _refresh(task_id):
    async with SessionLocal() as s:
        await jobs.pr_refresh(s, {"task_id": str(task_id)})
        await s.commit()


async def _row(task_id) -> TaskPullRequest | None:
    async with SessionLocal() as s:
        return await s.get(TaskPullRequest, task_id)


async def _to_finish_reviewed(db, tc, *, review=True, link=None):
    """The finish run queued, with human code review set before Done begins (it is frozen then)."""
    b, final = await _final_review(db, tc)
    if link is not None:
        link()
    if review:
        _patch_project(tc, require_human_code_review=True)
    await _review(final, "approved")
    await _finish(b.manager.id, final, "completed")
    run = await _last(b.task_id)
    assert run.workflow_role == "finish"
    return b, run


async def _finished_waiting(db, tc, github, *, review=True, url=PR):
    """A tracked pull request reported by the finish run; with review on, the workflow waits on it."""
    conn = await _connection(db)
    b, run = await _to_finish_reviewed(db, tc, review=review, link=lambda: _link(tc, conn))
    github.set()
    await _report(run, pr_url=url)
    await _finish(b.manager.id, run, "completed")
    return b, conn


async def test_pr_url_matching_matrix(db, tc_factory):
    tc = tc_factory(lifespan=True)
    from tests.workflow.test_engine import _board

    b = await _board(db, tc)
    conn = await _connection(db)
    other_host = await _connection(db, name="Other", base="https://other.example")
    _link(tc, conn)
    _link(tc, None, url=f"{BASE}/acme/unlinked", name="unlinked")  # no connection
    project_id = uuid.UUID(tc.get("/api/projects/PAY").json()["id"])
    async with SessionLocal() as s:
        found = await service.match_pr(s, project_id, PR)
        assert found is not None and found[0].id == conn.id and found[1].number == 7
        for url in (f"{BASE}/acme/unlinked/pull/7", f"{BASE}/acme/other/pull/7", "https://other.example/acme/pay/pull/7",
                    f"{BASE}/acme/pay/pull/", "javascript:alert(1)", f"{BASE}/acme/pay/pull/7?x", ""):
            assert await service.match_pr(s, project_id, url) is None, url
    assert other_host and b


async def test_report_finish_tracks_pr_and_refresh_reaches_status(db, tc_factory, github):
    tc = tc_factory(lifespan=True)
    conn = await _connection(db)
    b, run = await _to_finish(db, tc)
    _link(tc, conn)
    github.set(runs=[("in_progress", None)])
    await _report(run, pr_url=PR)
    row = await _row(b.task_id)
    assert (row.url, row.connection_id, row.state) == (PR, conn.id, "open")
    queued = (await db.execute(select(Job.dedupe_key).where(Job.kind == "git.pr_refresh"))).scalars().all()
    assert queued == [f"git.pr_refresh:{b.task_id}"]
    await _refresh(b.task_id)
    row = await _row(b.task_id)
    assert (row.state, row.checks, row.review, row.error, row.head_sha) == ("open", "pending", "none", None, "abc123")
    [ev] = await _events(b.task_id, "pr.status")
    assert ev.data == {"state": "open", "checks": "pending", "review": "none"}
    task = tc.get(f"/api/tasks/{b.key}").json()
    assert task["pull_request"] == {"url": PR, "state": "open", "checks": "pending", "review": "none", "tracked": True}
    assert tc.get(f"/api/tasks/{b.key}/workflow").json()["pull_request"]["tracked"] is True
    await _refresh(b.task_id)
    assert len(await _events(b.task_id, "pr.status")) == 1  # nothing changed, nothing recorded


async def test_merged_pr_finishes_waiting_workflow(db, tc_factory, github):
    tc = tc_factory(lifespan=True)
    b, _conn = await _finished_waiting(db, tc, github)
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "human_code_review")
    await _refresh(b.task_id)
    assert (await _wf(b.task_id)).status == "waiting_human"  # still open
    github.set(state="closed", merged=True, runs=[("completed", "success")])
    await _refresh(b.task_id)
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("finished", None)
    assert len(await _events(b.task_id, "pr.merged")) == 1
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "git.pr_merged"))).scalars().all()
    assert tc.get(f"/api/tasks/{b.key}").json()["column_id"] == b.cols["done"]["id"]
    await _refresh(b.task_id)  # merged rows are left alone afterwards
    assert len(await _events(b.task_id, "pr.merged")) == 1


async def test_pr_merged_before_finish_run_ends(db, tc_factory, github):
    tc = tc_factory(lifespan=True)
    conn = await _connection(db)
    b, run = await _to_finish_reviewed(db, tc, link=lambda: _link(tc, conn))
    github.set(state="closed", merged=True)
    await _report(run, pr_url=PR)
    await _refresh(b.task_id)  # merged while the finish run still runs: nothing waits yet
    assert (await _wf(b.task_id)).status == "running"
    await _finish(b.manager.id, run, "completed")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("finished", None)  # never waits on a PR already merged


async def test_closed_pr_escalates_and_accept_or_retry(db, tc_factory, github):
    tc = tc_factory(lifespan=True)
    b, _conn = await _finished_waiting(db, tc, github)
    github.set(state="closed")
    await _refresh(b.task_id)
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "pr_closed")
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "retry"})
    assert r.status_code == 200, r.text
    assert (await _last(b.task_id)).workflow_role == "finish"


async def test_closed_pr_accept_finishes(db, tc_factory, github):
    tc = tc_factory(lifespan=True)
    b, _conn = await _finished_waiting(db, tc, github)
    github.set(state="closed")
    await _refresh(b.task_id)
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "accept"})
    assert r.status_code == 200, r.text
    assert (await _wf(b.task_id)).status == "finished"


async def test_no_human_review_still_shows_status(db, tc_factory, github):
    tc = tc_factory(lifespan=True)
    b, _conn = await _finished_waiting(db, tc, github, review=False)
    assert (await _wf(b.task_id)).status == "finished"
    github.set(state="closed", merged=True)
    await _refresh(b.task_id)
    assert (await _row(b.task_id)).state == "merged" and (await _wf(b.task_id)).status == "finished"
    assert tc.get(f"/api/tasks/{b.key}").json()["pull_request"]["state"] == "merged"


@pytest.mark.parametrize("failure", [401, 404, 429, httpx.ConnectTimeout("slow"), "garbage"])
async def test_poll_errors_keep_state_and_back_off(db, tc_factory, github, failure):
    tc = tc_factory(lifespan=True)
    b, _conn = await _finished_waiting(db, tc, github)
    github.fail = failure
    expected = {401: "unauthorized", 404: "not_found", 429: "rate_limited"}.get(failure, None)
    for n, minutes in ((1, 2), (2, 4), (3, 8)):
        before = datetime.now(UTC)
        await _refresh(b.task_id)
        row = await _row(b.task_id)
        assert row.state == "open" and row.failures == n
        assert row.error == (expected or ("unreachable" if isinstance(failure, Exception) else "bad_response"))
        ahead = row.next_check_at - before
        assert timedelta(minutes=minutes) - timedelta(seconds=5) <= ahead <= timedelta(minutes=minutes, seconds=30)
    async with SessionLocal() as s:
        await s.execute(update(TaskPullRequest).values(failures=10))
        await s.commit()
    await _refresh(b.task_id)
    assert (await _row(b.task_id)).next_check_at - datetime.now(UTC) <= timedelta(minutes=60, seconds=5)
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "human_code_review")
    r = tc.post(f"/api/tasks/{b.key}/workflow/human-review", json={"approved": True})
    assert r.status_code == 200 and r.json()["status"] == "finished"


async def test_poll_picks_open_rows_oldest_first_limit_50(db, tc_factory, github, monkeypatch):
    tc = tc_factory(lifespan=True)
    b, conn = await _finished_waiting(db, tc, github)
    from app.tasks.models import Task

    task = await db.get(Task, b.task_id)
    now = datetime.now(UTC)
    extra = []
    for i in range(55):
        t = Task(project_id=task.project_id, number=1000 + i, type="task", title=f"t{i}", column_id=task.column_id,
                 position=float(i))
        db.add(t)
        await db.flush()
        db.add(TaskPullRequest(task_id=t.id, url=PR, connection_id=conn.id, state="open",
                               next_check_at=now - timedelta(minutes=60 - i)))
        extra.append(t.id)
    await db.commit()
    async with SessionLocal() as s:
        await s.execute(update(TaskPullRequest).where(TaskPullRequest.task_id == b.task_id)
                        .values(state="merged", next_check_at=now - timedelta(days=1)))
        await s.commit()
    refreshed: list[uuid.UUID] = []

    async def record(db, row):
        refreshed.append(row.task_id)

    monkeypatch.setattr(service, "refresh_pr", record)
    async with SessionLocal() as s:
        await jobs.pr_poll(s, {})
    assert refreshed == extra[:50]  # oldest first, 50 at most, merged rows skipped


async def test_plain_git_branch_pushed_and_mark_merged(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _to_finish_reviewed(
        db, tc, link=lambda: _link(tc, None, url="git@intranet:pay.git", name="pay", provider="plain"))
    await _report(run, outcome="branch_pushed", pr_url=None)
    await _finish(b.manager.id, run, "completed")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.finish_outcome, wf.pr_url) == ("waiting_human", "human_code_review", "branch_pushed", None)
    assert await _row(b.task_id) is None
    r = tc.post(f"/api/tasks/{b.key}/workflow/human-review", json={"approved": True})
    assert r.status_code == 200 and r.json()["status"] == "finished"


async def test_github_project_still_needs_a_pr_url(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _b, run = await _to_finish(db, tc)
    _link(tc, None, url="https://github.com/acme/pay", name="pay", provider="github")
    with pytest.raises(HTTPException) as e:
        await _report(run, outcome="branch_pushed", pr_url=None)
    assert (e.value.status_code, e.value.detail) == (422, "wrong_finish")
    with pytest.raises(HTTPException) as e:
        await _report(run, pr_url=None)
    assert (e.value.status_code, e.value.detail) == (422, "pr_url_required")


def test_finish_text_names_branch_pushed_and_tea():
    text = (DEFAULTS_DIR / "finish.md").read_text(encoding="utf-8")
    assert "branch_pushed" in text and "tea pulls create" in text and "gh pr create" in text


async def test_finish_handlers_registered_for_pr_closed():
    from app.workflow import engine

    assert engine.ACCEPT_HANDLERS["pr_closed"] is finish._accept_pr_closed
    assert (await _runs(uuid.uuid4())) == []
