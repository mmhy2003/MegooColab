"""Pull request and branch events on the task's Activity (piece 2): each delivery finds its task by the task's
branch, a pull request seen opened from it, or a tracked one; it names an agent or a person; a review's line
comments fold into it."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.agents.models import Agent
from app.core.crypto import encrypt
from app.core.db import SessionLocal
from app.git.models import GitConnection, TaskPullRequest
from app.projects.models import BoardColumn, Project, ProjectRepository
from app.tasks.models import Task, TaskEvent
from tests.factories import make_project

SECRET = "repo-secret"
BASE = "https://github.com"
REPO = {"full_name": "acme/pay"}
BRANCH = "megoo/PAY-1-retries"
PR = {"number": 1, "html_url": f"{BASE}/acme/pay/pull/1", "title": "Retries", "head": {"ref": BRANCH},
      "base": {"ref": "main"}, "merged": False}


async def _world(client, db):
    """PAY (task PAY-1) with repository acme/pay on a GitHub connection, its own webhook secret set."""
    _, manager, _ = await make_project(client, db, "PAY")
    project = (await db.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
    conn = GitConnection(name="GitHub", kind="github", base_url=BASE, token_enc=encrypt("t"))
    db.add(conn)
    await db.flush()
    repo = ProjectRepository(project_id=project.id, name="acme/pay", url=f"{BASE}/acme/pay", provider="github",
                             connection_id=conn.id, webhook_secret_enc=encrypt(SECRET))
    col = (await db.execute(select(BoardColumn.id).where(BoardColumn.project_id == project.id).limit(1))).scalar()
    task = Task(project_id=project.id, number=1, type="task", title="Retries", column_id=col, position=1.0)
    db.add_all([repo, task])
    await db.commit()
    return conn, repo, task, manager


_n = 0


async def _send(client, repo, event: str, payload: dict, delivery: str | None = None):
    global _n
    _n += 1
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "X-GitHub-Event": event,
               "X-Hub-Signature-256": "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
               "X-GitHub-Delivery": delivery or f"d-{uuid.uuid4()}-{_n}"}
    r = await client.post(f"/api/git/webhooks/repos/{repo.id}", content=body, headers=headers)
    assert r.status_code == 204, r.text


def _push(branch=BRANCH, who="mo", commits=1, repo=REPO) -> dict:
    return {"ref": f"refs/heads/{branch}", "after": "a" * 40, "compare": f"{BASE}/acme/pay/compare/x", "repository": repo,
            "pusher": {"name": who}, "commits": [{"message": f"commit {i}"} for i in range(commits)]}


def _pr(action: str, who="mo", **pr) -> dict:
    return {"action": action, "pull_request": {**PR, **pr}, "repository": REPO, "sender": {"login": who}}


async def _git(task_id) -> list[TaskEvent]:
    async with SessionLocal() as s:
        rows = await s.execute(select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.kind.like("git.%"))
                               .order_by(TaskEvent.created_at, TaskEvent.id))
        return list(rows.scalars())


async def _run(task, owner, *, status="running", finished_ago: timedelta | None = None) -> Agent:
    async with SessionLocal() as s:
        agent = Agent(owner_id=owner.id, name="laptop-claude", program="claude_code")
        s.add(agent)
        await s.flush()
        now = datetime.now(UTC)
        s.add(AgentRun(task_id=task.id, agent_id=agent.id, requested_by=owner.id, policy="read_write", prompt="p",
                       status=status, started_at=now - timedelta(minutes=20),
                       finished_at=None if finished_ago is None else now - finished_ago))
        await s.commit()
        return agent


async def test_push_to_the_task_branch_is_recorded_as_a_person(client, db):
    _, repo, task, _ = await _world(client, db)
    await _send(client, repo, "push", _push())
    await _send(client, repo, "push", _push(branch="main"))
    (e,) = await _git(task.id)
    assert e.kind == "git.pushed" and e.actor_user_id is None
    assert e.data["actor"] == {"kind": "person", "name": "mo", "login": "mo"}
    assert (e.data["host"], e.data["commits"], e.data["branch"], e.data["pr"]) == ("github", 1, BRANCH, None)


async def test_push_and_pr_opened_during_an_agent_run_are_the_agent(client, db):
    _, repo, task, owner = await _world(client, db)
    agent = await _run(task, owner)
    await _send(client, repo, "push", _push())
    await _send(client, repo, "pull_request", _pr("opened"))
    pushed, opened = await _git(task.id)
    want = {"kind": "agent", "agent_id": str(agent.id), "name": "laptop-claude", "login": "mo"}
    assert pushed.data["actor"] == want and opened.data["actor"] == want
    assert opened.data["pr"] == {"number": 1, "url": PR["html_url"]}
    assert (opened.data["branch"], opened.data["base"], opened.data["title"]) == (BRANCH, "main", "Retries")


async def test_an_agent_run_finished_within_five_minutes_still_counts(client, db):
    _, repo, task, owner = await _world(client, db)
    await _run(task, owner, status="completed", finished_ago=timedelta(minutes=4))
    await _send(client, repo, "push", _push())
    assert (await _git(task.id))[0].data["actor"]["kind"] == "agent"


async def test_an_agent_run_finished_long_ago_does_not(client, db):
    _, repo, task, owner = await _world(client, db)
    await _run(task, owner, status="completed", finished_ago=timedelta(minutes=6))
    await _send(client, repo, "push", _push())
    assert (await _git(task.id))[0].data["actor"]["kind"] == "person"


async def test_pr_opened_links_the_pr_so_comments_and_merge_find_the_task(client, db):
    _, repo, task, _ = await _world(client, db)
    await _send(client, repo, "pull_request", _pr("opened"))
    await _send(client, repo, "issue_comment", {
        "action": "created", "repository": REPO, "sender": {"login": "rev"}, "issue": {"number": 1, "pull_request": {}},
        "comment": {"body": "Can we log the retry count?", "html_url": f"{BASE}/acme/pay/pull/1#c1"}})
    await _send(client, repo, "pull_request", _pr("closed", merged=True, head={"ref": "renamed"}))
    _opened, commented, merged = await _git(task.id)
    assert commented.kind == "git.commented" and commented.data["excerpt"] == "Can we log the retry count?"
    assert commented.data["actor"] == {"kind": "person", "name": "rev", "login": "rev"}
    assert merged.kind == "git.pr_merged" and merged.data["actor"]["name"] == "mo"
    assert merged.data["pr"] == {"number": 1, "url": PR["html_url"]}


async def test_a_tracked_pr_is_found_without_a_branch(client, db):
    conn, repo, task, _ = await _world(client, db)
    async with SessionLocal() as s:
        s.add(TaskPullRequest(task_id=task.id, url=PR["html_url"], connection_id=conn.id, state="open"))
        await s.commit()
    await _send(client, repo, "issue_comment", {
        "action": "created", "repository": REPO, "sender": {"login": "rev"}, "issue": {"number": 1, "pull_request": {}},
        "comment": {"body": "hi", "html_url": f"{BASE}/c/1"}})
    (e,) = await _git(task.id)
    assert e.kind == "git.commented" and e.data["pr"]["number"] == 1


async def test_push_says_the_pr_was_updated(client, db):
    _, repo, task, _ = await _world(client, db)
    await _send(client, repo, "pull_request", _pr("opened"))
    await _send(client, repo, "push", _push(commits=2))
    pushed = (await _git(task.id))[-1]
    assert pushed.kind == "git.pushed" and pushed.data["pr"] == {"number": 1, "url": PR["html_url"]}
    await _send(client, repo, "pull_request", _pr("closed"))
    await _send(client, repo, "push", _push())
    assert (await _git(task.id))[-1].data["pr"] is None  # closed: no longer "updated"


async def test_a_line_comment_before_its_review_makes_one_entry(client, db):
    _, repo, task, _ = await _world(client, db)
    await _send(client, repo, "pull_request", _pr("opened"))

    def line(path, n, body):
        return {"action": "created", "repository": REPO, "sender": {"login": "rev"}, "pull_request": PR,
                "comment": {"pull_request_review_id": 9, "path": path, "line": n, "body": body,
                            "html_url": f"{BASE}/c/{n}"}}

    await _send(client, repo, "pull_request_review_comment", line("src/a.py", 88, "Add a delay"))
    await _send(client, repo, "pull_request_review_comment", line("src/b.py", 4, "Twice"))
    await _send(client, repo, "pull_request_review", {
        "action": "submitted", "repository": REPO, "sender": {"login": "rev"}, "pull_request": PR,
        "review": {"id": 9, "state": "changes_requested", "body": "Two things", "html_url": f"{BASE}/r/9"}})
    reviews = [e for e in await _git(task.id) if e.kind == "git.reviewed"]
    assert len(reviews) == 1 and not [e for e in await _git(task.id) if e.kind == "git.review_comment"]
    data = reviews[0].data
    assert (data["verdict"], data["excerpt"], data["comments"], data["url"]) == ("changes_requested", "Two things", 2,
                                                                                f"{BASE}/r/9")
    assert data["first"] == {"file": "src/a.py", "line": 88, "excerpt": "Add a delay", "url": f"{BASE}/c/88"}
    assert data["actor"]["name"] == "rev"


async def test_a_branch_of_a_project_without_this_repository_is_ignored(client, db):
    _, repo, task, _ = await _world(client, db)
    other = await make_project(client, db, "OTHER")
    async with SessionLocal() as s:
        project = (await s.execute(select(Project).where(Project.key == "OTHER"))).scalar_one()
        col = (await s.execute(select(BoardColumn.id).where(BoardColumn.project_id == project.id).limit(1))).scalar()
        task2 = Task(project_id=project.id, number=1, type="task", title="x", column_id=col, position=1.0)
        s.add(task2)
        await s.commit()
    assert other
    await _send(client, repo, "push", _push(branch="megoo/OTHER-1-x"))
    assert await _git(task2.id) == [] and await _git(task.id) == []


async def test_a_delivery_naming_another_repository_is_ignored(client, db):
    _, repo, task, _ = await _world(client, db)
    await _send(client, repo, "push", _push(repo={"full_name": "acme/web"}))
    assert await _git(task.id) == []


async def test_a_repeated_delivery_records_once(client, db):
    _, repo, task, _ = await _world(client, db)
    await _send(client, repo, "push", _push(), delivery="same")
    await _send(client, repo, "push", _push(), delivery="same")
    assert len(await _git(task.id)) == 1


# -- checks, and one line per merge or close ----------------------------------------------------------------------


async def _apply(task_id, checks: str, sha: str | None) -> None:
    from app.git import providers, service

    async with SessionLocal() as s:
        status = providers.PrStatus(state="open", checks=checks, review="none", merged_at=None, head_sha=sha)
        await service.apply_status(s, task_id, "main", status)
        await s.commit()


async def test_checks_record_once_per_head_and_result(client, db):
    conn, _, task, _ = await _world(client, db)
    async with SessionLocal() as s:
        s.add(TaskPullRequest(task_id=task.id, url=PR["html_url"], connection_id=conn.id, state="open"))
        await s.commit()
    for checks, sha in [("pending", "a"), ("success", "a"), ("success", "a"), ("pending", "b"), ("failure", "b")]:
        await _apply(task.id, checks, sha)
    entries = [e.data for e in await _git(task.id) if e.kind == "git.checks"]
    assert [(e["result"], e["head_sha"]) for e in entries] == [("passed", "a"), ("failed", "b")]
    assert entries[0]["pr"] == {"number": 1, "url": PR["html_url"]} and entries[0]["host"] == "github"
    assert entries[0]["actor"] is None


async def _feed(client, key="PAY-1") -> list[str]:
    r = await client.get(f"/api/tasks/{key}/activity")
    assert r.status_code == 200, r.text
    return [i["kind"] for i in r.json() if i["type"] == "event"]


async def _add(task, kind: str, data: dict, ago: int) -> None:
    async with SessionLocal() as s:
        s.add(TaskEvent(task_id=task.id, kind=kind, data=data, created_at=datetime.now(UTC) - timedelta(seconds=ago)))
        await s.commit()


async def test_pr_status_is_not_in_activity(client, db):
    _, _, task, _ = await _world(client, db)
    await _add(task, "pr.status", {"state": "open", "checks": "pending", "review": "none"}, 5)
    assert "pr.status" not in await _feed(client)


async def test_one_merge_line_whichever_comes_first(client, db):
    _, _, task, _ = await _world(client, db)
    url = PR["html_url"]
    await _add(task, "pr.merged", {"url": url}, 30)  # the poll first
    assert "pr.merged" in await _feed(client)  # poll only: the nameless line stays
    await _add(task, "git.pr_merged", {"pr": {"number": 1, "url": url + "/"}, "actor": {"kind": "person", "name": "mo"}}, 20)
    assert [k for k in await _feed(client) if "merged" in k] == ["git.pr_merged"]
    await _add(task, "pr.closed", {"url": "https://github.com/acme/pay/pull/2", "kind": "main"}, 10)  # webhook-less close
    await _add(task, "git.pr_closed", {"pr": {"number": 3, "url": "https://github.com/acme/pay/pull/3"}}, 9)
    await _add(task, "pr.closed", {"url": "https://github.com/acme/pay/pull/3", "kind": "main"}, 8)  # then the poll
    assert [k for k in await _feed(client) if "closed" in k] == ["pr.closed", "git.pr_closed"]


# -- the final review's findings ---------------------------------------------------------------------------------


async def test_a_task_number_too_large_is_ignored(client, db):
    _, repo, task, _ = await _world(client, db)
    await _send(client, repo, "push", _push(branch="megoo/PAY-99999999999-x"))
    assert await _git(task.id) == []


async def test_a_failure_writing_activity_never_fails_the_delivery(client, db, monkeypatch):
    from app.git import activity
    from app.jobs.models import Job

    conn, repo, task, _ = await _world(client, db)
    async with SessionLocal() as s:
        s.add(TaskPullRequest(task_id=task.id, url=PR["html_url"], connection_id=conn.id, state="open"))
        await s.commit()

    async def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(activity, "record", broken)
    await _send(client, repo, "pull_request", _pr("closed", merged=True))  # 204, asserted in _send
    async with SessionLocal() as s:  # the refresh it asked for is still queued
        assert (await s.execute(select(Job.id).where(Job.kind == "git.pr_refresh"))).first() is not None


async def test_one_repository_in_two_projects_records_once(client, db):
    conn, repo, task, _ = await _world(client, db)
    await make_project(client, db, "WEB")
    async with SessionLocal() as s:
        web = (await s.execute(select(Project).where(Project.key == "WEB"))).scalar_one()
        twin = ProjectRepository(project_id=web.id, name="acme/pay", url=f"{BASE}/acme/pay", provider="github",
                                 connection_id=conn.id, webhook_secret_enc=encrypt(SECRET))
        s.add(twin)
        await s.commit()
    await _send(client, repo, "push", _push())
    await _send(client, twin, "push", _push())  # the host delivers the same push to both projects' webhooks
    assert len(await _git(task.id)) == 1


async def test_a_review_waits_for_its_line_comment_in_flight(client, db):
    """GitHub sends a review and its line comments at the same moment: the second delivery waits for the first
    (a lock on the task), so it folds into that entry rather than making its own."""
    import asyncio

    from app.git import activity, events
    from app.git.models import GitKind

    conn, repo, task, _ = await _world(client, db)
    gh = lambda event, payload: events.parse_delivery(GitKind.github, {"x-github-event": event}, payload)
    comment = gh("pull_request_review_comment", {
        "action": "created", "repository": REPO, "sender": {"login": "rev"}, "pull_request": PR,
        "comment": {"pull_request_review_id": 9, "path": "src/a.py", "line": 1, "body": "c1", "html_url": f"{BASE}/c/1"}})
    review = gh("pull_request_review", {
        "action": "submitted", "repository": REPO, "sender": {"login": "rev"}, "pull_request": PR,
        "review": {"id": 9, "state": "changes_requested", "body": "Two things"}})
    async with SessionLocal() as first, SessionLocal() as second:
        await activity.record(first, await first.get(GitConnection, conn.id), comment,
                              repo=await first.get(ProjectRepository, repo.id))  # in flight: not committed yet

        async def other():
            await activity.record(second, await second.get(GitConnection, conn.id), review,
                                  repo=await second.get(ProjectRepository, repo.id))
            await second.commit()

        waiting = asyncio.create_task(other())
        await asyncio.sleep(0.5)
        await first.commit()
        await asyncio.wait_for(waiting, 10)
    reviews = [e for e in await _git(task.id) if e.kind == "git.reviewed"]
    assert len(reviews) == 1
    assert (reviews[0].data["verdict"], reviews[0].data["comments"]) == ("changes_requested", 1)
