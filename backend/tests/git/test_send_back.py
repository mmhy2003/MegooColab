"""Changes requested on the task's pull request send the task back to its agent (piece 3): a "changes requested"
review or a /fix comment, with the project's checkbox on, while the workflow waits for the merge; at most 3 rounds
per pull request, then the human decides."""

import hashlib
import hmac
import json
import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.core.crypto import encrypt
from app.core.db import SessionLocal
from app.git.models import GitConnection, TaskPullRequest
from app.projects.models import BoardColumn, Project, ProjectRepository
from app.tasks.models import Task, TaskEvent
from app.workflow import engine, methodology
from app.workflow.models import Needs, Stage, TaskWorkflow, WorkflowStatus
from tests.factories import make_project

SECRET = "repo-secret"
BRANCH = "megoo/PAY-1-retries"


class World:
    def __init__(self, kind: str):
        self.kind = kind
        self.base = "https://lab.acme.io" if kind == "gitlab" else "https://github.com"
        self.pr_url = (f"{self.base}/acme/pay/-/merge_requests/1" if kind == "gitlab"
                       else f"{self.base}/acme/pay/pull/1")


async def _world(client, db, *, kind="github", on=True) -> tuple[World, ProjectRepository, Task]:
    """PAY-1, assigned to an agent, its workflow waiting for its pull request (#1) to merge."""
    w = World(kind)
    _, manager, _ = await make_project(client, db, "PAY")
    await methodology.seed_defaults(db)
    project = (await db.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
    project.send_back_on_changes_requested = on
    project.require_human_code_review = True
    conn = GitConnection(name="Host", kind=kind, base_url=w.base, token_enc=encrypt("t"))
    agent = Agent(owner_id=manager.id, name="laptop-claude", program="claude_code")
    db.add_all([conn, agent])
    await db.flush()
    repo = ProjectRepository(project_id=project.id, name="acme/pay", url=f"{w.base}/acme/pay", provider=kind,
                             connection_id=conn.id, webhook_secret_enc=encrypt(SECRET))
    col = (await db.execute(select(BoardColumn.id).where(BoardColumn.project_id == project.id).limit(1))).scalar()
    task = Task(project_id=project.id, number=1, type="task", title="Retries", column_id=col, position=1.0,
                assignee_agent_id=agent.id)
    db.add_all([repo, task])
    await db.flush()
    db.add_all([
        TaskWorkflow(task_id=task.id, stage=Stage.done, status=WorkflowStatus.waiting_human,
                     needs=Needs.human_code_review, agent_id=agent.id, branch=BRANCH, pr_url=w.pr_url,
                     finish_outcome="pr_opened", finish_requires_human_review=True, finishing_override="pull_request"),
        TaskPullRequest(task_id=task.id, url=w.pr_url, connection_id=conn.id, state="open"),
    ])
    await db.commit()
    return w, repo, task


async def _send(client, w: World, repo, event: str, payload: dict):
    body = json.dumps(payload).encode()
    if w.kind == "gitlab":
        headers = {"X-Gitlab-Event": event, "X-Gitlab-Token": SECRET, "Idempotency-Key": str(uuid.uuid4())}
    else:
        headers = {"X-GitHub-Event": event, "X-GitHub-Delivery": str(uuid.uuid4()),
                   "X-Hub-Signature-256": "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()}
    r = await client.post(f"/api/git/webhooks/repos/{repo.id}", content=body,
                          headers={"Content-Type": "application/json", **headers})
    assert r.status_code == 204, r.text


def _pr(w: World, number=1) -> dict:
    return {"number": number, "html_url": f"{w.base}/acme/pay/pull/{number}", "head": {"ref": BRANCH},
            "base": {"ref": "main"}}


def _review(w: World, verdict="changes_requested", assoc="COLLABORATOR", number=1, review_id=9, body="Two things"):
    return {"action": "submitted", "repository": {"full_name": "acme/pay"}, "sender": {"login": "rev"},
            "pull_request": _pr(w, number), "review": {"id": review_id, "state": verdict, "body": body,
                                                       "author_association": assoc}}


def _line(w: World, review_id=9, assoc="COLLABORATOR"):
    return {"action": "created", "repository": {"full_name": "acme/pay"}, "sender": {"login": "rev"},
            "pull_request": _pr(w), "comment": {"pull_request_review_id": review_id, "path": "src/a.py", "line": 88,
                                                "body": "Add a delay", "author_association": assoc}}


def _comment(body: str, assoc="COLLABORATOR"):
    return {"action": "created", "repository": {"full_name": "acme/pay"}, "sender": {"login": "mo"},
            "issue": {"number": 1, "pull_request": {}}, "comment": {"body": body, "author_association": assoc}}


async def _wf(task_id) -> TaskWorkflow:
    async with SessionLocal() as s:
        return await s.get(TaskWorkflow, task_id)


async def _kinds(task_id, kind: str) -> list[TaskEvent]:
    async with SessionLocal() as s:
        return list((await s.execute(select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.kind == kind)
                                     .order_by(TaskEvent.created_at))).scalars())


async def _fix_runs(task_id) -> list[AgentRun]:
    async with SessionLocal() as s:
        return list((await s.execute(select(AgentRun).where(AgentRun.task_id == task_id,
                                                           AgentRun.workflow_role == "pr_fix"))).scalars())


async def _back_to_waiting(task_id) -> None:
    """As if the fix run had pushed: the run is over, the workflow waits for the merge again."""
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.task_id == task_id).values(status=RunStatus.completed))
        await s.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == task_id).values(
            stage=Stage.done, status=WorkflowStatus.waiting_human, needs=Needs.human_code_review))
        await s.commit()


async def test_changes_requested_sends_the_task_back(client, db):
    w, repo, task = await _world(client, db)
    await _send(client, w, repo, "pull_request_review", _review(w))
    wf = await _wf(task.id)
    assert (wf.stage, wf.status, wf.needs, wf.pr_fix_rounds) == ("build", "running", None, 1)
    assert wf.pr_fix_trigger["by"] == "rev" and wf.pr_fix_trigger["kind"] == "review"
    (sent,) = await _kinds(task.id, "pr.sent_back")
    want = {"pr_url": w.pr_url, "pr_number": 1, "by": "rev", "kind": "review", "round": 1, "of": 3}
    assert {k: sent.data[k] for k in want} == want
    assert sent.data["excerpt"] == "Two things"
    (run,) = await _fix_runs(task.id)
    assert run.status == RunStatus.queued


async def test_fix_comment_sends_back_and_other_comments_dont(client, db):
    w, repo, task = await _world(client, db)
    for body in ("please /fix", "/fixed it", "LGTM"):
        await _send(client, w, repo, "issue_comment", _comment(body))
    assert await _kinds(task.id, "pr.sent_back") == []
    await _send(client, w, repo, "issue_comment", _comment("  /FIX add a delay between retries"))
    (sent,) = await _kinds(task.id, "pr.sent_back")
    assert (sent.data["kind"], sent.data["by"]) == ("fix_comment", "mo")
    assert sent.data["excerpt"].endswith("add a delay between retries")


async def test_nothing_without_the_checkbox(client, db):
    w, repo, task = await _world(client, db, on=False)
    await _send(client, w, repo, "pull_request_review", _review(w))
    assert await _kinds(task.id, "pr.sent_back") == [] and (await _wf(task.id)).stage == "done"


async def test_nothing_unless_waiting_for_the_merge(client, db):
    w, repo, task = await _world(client, db)
    for status in (WorkflowStatus.running, WorkflowStatus.finished):
        async with SessionLocal() as s:
            await s.execute(update(TaskWorkflow).values(status=status, needs=None))
            await s.commit()
        await _send(client, w, repo, "pull_request_review", _review(w, review_id=hash(status) % 1000))
    assert await _kinds(task.id, "pr.sent_back") == [] and await _fix_runs(task.id) == []


async def test_github_needs_write_access(client, db):
    w, repo, task = await _world(client, db)
    await _send(client, w, repo, "pull_request_review", _review(w, assoc="NONE", review_id=1))
    await _send(client, w, repo, "issue_comment", _comment("/fix it", assoc="CONTRIBUTOR"))
    assert await _kinds(task.id, "pr.sent_back") == []
    await _send(client, w, repo, "issue_comment", _comment("/fix it", assoc="MEMBER"))
    assert len(await _kinds(task.id, "pr.sent_back")) == 1


async def test_gitlab_fix_note_sends_back(client, db):
    w, repo, task = await _world(client, db, kind="gitlab")
    await _send(client, w, repo, "Note Hook", {
        "object_kind": "note", "project": {"path_with_namespace": "acme/pay"}, "user": {"name": "Mo", "username": "mo"},
        "object_attributes": {"noteable_type": "MergeRequest", "note": "/fix the timeout", "url": f"{w.pr_url}#note_1"},
        "merge_request": {"iid": 1, "source_branch": BRANCH}})
    (sent,) = await _kinds(task.id, "pr.sent_back")
    assert sent.data["pr_number"] == 1 and sent.data["by"] == "Mo"


async def test_a_review_sends_back_once_whichever_part_arrives_first(client, db):
    w, repo, task = await _world(client, db)
    await _send(client, w, repo, "pull_request_review_comment", _line(w))
    assert await _kinds(task.id, "pr.sent_back") == []  # only a line comment so far: a "commented" review
    await _send(client, w, repo, "pull_request_review", _review(w))
    await _back_to_waiting(task.id)
    await _send(client, w, repo, "pull_request_review_comment", _line(w))  # a late part of the same review
    assert len(await _kinds(task.id, "pr.sent_back")) == 1


async def test_a_trigger_about_another_pr_does_nothing(client, db):
    w, repo, task = await _world(client, db)
    await _send(client, w, repo, "pull_request_review", _review(w, number=5))  # same task branch, another PR
    assert await _kinds(task.id, "pr.sent_back") == []


async def test_the_fourth_trigger_escalates(client, db):
    w, repo, task = await _world(client, db)
    for n in range(3):
        await _send(client, w, repo, "pull_request_review", _review(w, review_id=100 + n))
        assert (await _wf(task.id)).pr_fix_rounds == n + 1
        await _back_to_waiting(task.id)
    await _send(client, w, repo, "pull_request_review", _review(w, review_id=200))
    wf = await _wf(task.id)
    assert (wf.status, wf.needs, wf.escalation_reason) == ("waiting_human", "escalation", "pr_fix_rounds_exhausted")
    assert len(await _fix_runs(task.id)) == 3 and len(await _kinds(task.id, "pr.sent_back")) == 3


async def test_rounds_start_again_for_a_new_pr(client, db):
    w, repo, task = await _world(client, db)
    new_pr = f"{w.base}/acme/pay/pull/2"
    async with SessionLocal() as s:
        await s.execute(update(TaskWorkflow).values(pr_fix_rounds=3, pr_fix_pr_url=w.pr_url, pr_url=new_pr))
        await s.execute(update(TaskPullRequest).values(url=new_pr))
        await s.commit()
    await _send(client, w, repo, "pull_request_review", _review(w, number=2))
    wf = await _wf(task.id)
    assert (wf.pr_fix_rounds, wf.pr_fix_pr_url, wf.stage) == (1, new_pr, "build")


async def test_a_trigger_dispatches_the_fix_run(client, db, monkeypatch):
    w, repo, _ = await _world(client, db)
    seen: list[bool] = []
    real = engine.dispatch_queued

    async def spy(session):
        seen.append(bool(session.info.get(engine._DISPATCH_KEY)))
        await real(session)

    monkeypatch.setattr(engine, "dispatch_queued", spy)
    await _send(client, w, repo, "pull_request_review", _review(w))
    assert seen[:1] == [True]  # the delivery's own call found the queued run (dispatching may call it again)


# -- the fix run (Task 3) ------------------------------------------------------------------------------------


async def _owner(task) -> "uuid.UUID":
    async with SessionLocal() as s:
        return await s.scalar(select(Agent.owner_id).where(Agent.id == task.assignee_agent_id))


async def _report(run, summary="Added a back-off", tests_passed=True) -> None:
    from app.git import send_back

    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run.id).values(status="running"))
        await send_back.report_fix(s, await s.get(AgentRun, run.id), summary, tests_passed)
        await s.commit()


async def test_fix_run_prompt_names_the_pr_and_the_request(client, db):
    w, repo, task = await _world(client, db)
    await _send(client, w, repo, "pull_request_review", _review(w, body="Add a <back-off>"))
    (run,) = await _fix_runs(task.id)
    assert run.prompt.startswith("# Fix: address the changes requested on the pull request")
    assert "## Changes requested on the pull request" in run.prompt
    assert f"Pull request: {w.pr_url} (branch {BRANCH}) · round 1 of 3" in run.prompt
    assert 'rev asked: "Add a &lt;back-off&gt;"' in run.prompt and '<untrusted source="pull request review">' in run.prompt


async def test_fix_reported_with_passing_tests_waits_for_the_merge_again(client, db):
    from tests.workflow.test_engine import _finish

    w, repo, task = await _world(client, db)
    await _send(client, w, repo, "pull_request_review", _review(w))
    (run,) = await _fix_runs(task.id)
    await _report(run)
    await _finish(await _owner(task), run)
    wf = await _wf(task.id)
    assert (wf.stage, wf.status, wf.needs) == ("done", "waiting_human", "human_code_review")
    (pushed,) = await _kinds(task.id, "pr.fix_pushed")
    assert {k: pushed.data[k] for k in ("pr_url", "pr_number", "round", "of", "summary")} == {
        "pr_url": w.pr_url, "pr_number": 1, "round": 1, "of": 3, "summary": "Added a back-off"}


async def test_fix_without_a_report_nudges_then_escalates(client, db):
    from tests.workflow.test_engine import _finish

    w, repo, task = await _world(client, db)
    await _send(client, w, repo, "pull_request_review", _review(w))
    (run,) = await _fix_runs(task.id)
    await _finish(await _owner(task), run)
    runs = await _fix_runs(task.id)
    assert len(runs) == 2  # the nudge
    nudge = next(r for r in runs if r.id != run.id)
    await _report(nudge, tests_passed=False)
    await _finish(await _owner(task), nudge)
    wf = await _wf(task.id)
    assert (wf.needs, wf.escalation_reason) == ("escalation", "pr_fix_incomplete")


async def test_accept_returns_to_waiting_for_the_merge(client, db):
    from app.auth.models import User

    _, _, task = await _world(client, db)
    for reason in ("pr_fix_rounds_exhausted", "pr_fix_incomplete"):
        async with SessionLocal() as s:
            await s.execute(update(TaskWorkflow).values(status="waiting_human", needs="escalation",
                                                        escalation_reason=reason, stage="build"))
            await s.commit()
        async with SessionLocal() as s:
            user = await s.get(User, await _owner(task))
            await engine.decide_escalation(s, user, await s.get(Task, task.id), "accept")
            await s.commit()
        wf = await _wf(task.id)
        assert (wf.stage, wf.status, wf.needs) == ("done", "waiting_human", "human_code_review"), reason


# -- "Don't send back" (Task 4) ---------------------------------------------------------------------------------


async def test_dont_send_back_cancels_without_a_rerun(client, db):
    w, repo, task = await _world(client, db)
    await _send(client, w, repo, "pull_request_review", _review(w))  # the manager (the agent's owner) is logged in
    r = await client.post("/api/tasks/PAY-1/workflow/send-back/cancel")
    assert r.status_code == 200, r.text
    wf = await _wf(task.id)
    assert (wf.stage, wf.status, wf.needs, wf.pr_fix_rounds) == ("done", "waiting_human", "human_code_review", 1)
    (run,) = await _fix_runs(task.id)
    assert run.status == RunStatus.cancelled
    (stopped,) = await _kinds(task.id, "pr.send_back_cancelled")
    assert stopped.actor_user_id == await _owner(task)


async def test_dont_send_back_needs_a_fix_running(client, db):
    await _world(client, db)
    r = await client.post("/api/tasks/PAY-1/workflow/send-back/cancel")
    assert r.status_code == 409 and r.json()["detail"] == "no_fix_running"
