"""Following a task's pull request (GIT-3, GIT-5) and what it means for the Done stage (WF-6a).

A pull request is tracked only when its URL is on the base URL of a connection linked to one of the task's
project repositories, and names that repository. Its state always comes from the provider API with the
connection's read-only token (webhooks only trigger a refresh). A provider error keeps the last known state and
backs off; it never finishes or escalates anything.

While a workflow waits on `human_code_review`: merged -> finished; closed -> escalation `pr_closed`. A production
fix (Branch from) has two rows, its own pull request and the back-merge into the default branch: it finishes only
when both are merged, and either one closed escalates (`back_merge_pr_closed` for the back-merge one).
"""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.git import providers
from app.git.models import PR_BACK_MERGE, PR_MAIN, GitConnection, TaskPullRequest
from app.jobs import queue
from app.projects.models import ProjectRepository
from app.tasks.models import Task

POLL_SECONDS = 120
POLL_LIMIT = 50
MAX_BACKOFF_MINUTES = 60


def _now() -> datetime:
    return datetime.now(UTC)


def _same_repo(conn: GitConnection, repo_url: str, ref: providers.PrRef) -> bool:
    path = providers.repo_path(repo_url)
    if path is None:
        return False
    prefix = urlsplit(conn.base_url).path.strip("/")
    return path == ref.path or (bool(prefix) and path == f"{prefix}/{ref.path}")


async def match_pr(db: AsyncSession, project_id: uuid.UUID, url: str) -> tuple[GitConnection, providers.PrRef] | None:
    """The connection that follows this pull request URL for the project, or None (untracked)."""
    repos = (
        await db.execute(
            select(ProjectRepository).where(
                ProjectRepository.project_id == project_id, ProjectRepository.connection_id.is_not(None)
            )
        )
    ).scalars().all()
    for repo in repos:
        conn = await db.get(GitConnection, repo.connection_id)
        if conn is None:
            continue
        ref = providers.parse_pr_url(url, conn)
        if ref is not None and _same_repo(conn, repo.url, ref):
            return conn, ref
    return None


async def queue_refresh(db: AsyncSession, task_id: uuid.UUID) -> None:
    await queue.enqueue(db, "git.pr_refresh", {"task_id": str(task_id)}, dedupe_key=f"git.pr_refresh:{task_id}")


async def track_pr(db: AsyncSession, task: Task, url: str, kind: str = PR_MAIN) -> TaskPullRequest:
    """The Finish run reported a pull request: (re)start following it. A new report replaces the old one."""
    found = await match_pr(db, task.project_id, url)
    row = await db.get(TaskPullRequest, (task.id, kind))
    if row is None:
        row = TaskPullRequest(task_id=task.id, kind=kind)
        db.add(row)
    row.url = url
    row.connection_id = found[0].id if found else None
    row.state, row.checks, row.review = "open", "none", "none"
    row.merged_at = row.head_sha = row.error = row.last_checked_at = None
    row.failures = 0
    row.next_check_at = _now()
    await db.flush()
    if found:
        await queue_refresh(db, task.id)
    return row


async def refresh_pr(db: AsyncSession, row: TaskPullRequest) -> str | None:
    """Read the pull request from the provider (outside any lock), then apply what changed. Returns the error
    code when it could not be read; the row then waits longer before the next try."""
    conn = await db.get(GitConnection, row.connection_id) if row.connection_id else None
    if conn is None:
        return None
    task_id, kind = row.task_id, row.kind
    ref = providers.parse_pr_url(row.url, conn)
    if ref is None:  # the connection's base URL changed since the pull request was reported
        await back_off(db, task_id, kind, "url_mismatch")
        return "url_mismatch"
    try:
        status = await providers.fetch_pr(conn, ref)
    except providers.GitProviderError as e:
        await back_off(db, task_id, kind, e.code)
        return e.code
    await apply_status(db, task_id, kind, status, url=row.url)
    return None


async def back_off(db: AsyncSession, task_id: uuid.UUID, kind: str, code: str) -> None:
    """A failed check: remember why, and wait 2, 4, 8 ... up to 60 minutes before the next one."""
    locked = await _lock_row(db, task_id, kind)
    if locked is not None:
        locked.failures += 1
        locked.error = code
        locked.last_checked_at = _now()
        locked.next_check_at = _now() + timedelta(minutes=min(2 ** locked.failures, MAX_BACKOFF_MINUTES))
        await db.flush()


async def _lock_row(db: AsyncSession, task_id: uuid.UUID, kind: str) -> TaskPullRequest | None:
    return (
        await db.execute(
            select(TaskPullRequest).where(TaskPullRequest.task_id == task_id, TaskPullRequest.kind == kind)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def apply_status(
    db: AsyncSession, task_id: uuid.UUID, kind: str, status: providers.PrStatus, *, url: str | None = None
) -> None:
    """Store the provider's view; on a change, record it and move a waiting Done stage on. `url`: the pull request
    that was read; a report of another one since then makes this view stale."""
    from app.workflow import engine  # local: the workflow imports this module

    task = await db.get(Task, task_id)
    if task is None:
        return
    wf = await engine.lock_task(db, task)  # the engine's lock order: task, workflow, then our row
    row = await _lock_row(db, task_id, kind)
    if row is None or (url is not None and row.url != url):
        return
    changed = (row.state, row.checks, row.review) != (status.state, status.checks, status.review)
    row.state, row.checks, row.review = status.state, status.checks, status.review
    row.merged_at, row.head_sha = status.merged_at, status.head_sha
    # a pull request of another branch is shown, but never stands in for the task's own (GIT-5)
    own = None if wf is None else wf.back_merge_branch if kind == PR_BACK_MERGE else wf.branch
    other_branch = bool(own and status.head_branch and status.head_branch != own)
    row.error, row.failures = ("branch_mismatch" if other_branch else None), 0
    row.last_checked_at = _now()
    row.next_check_at = _now() + timedelta(seconds=POLL_SECONDS)
    await db.flush()
    if not changed:
        return
    await engine.record_workflow_event(db, task, None, "pr.status",
                                       {"state": status.state, "checks": status.checks, "review": status.review})
    if wf is not None:
        await settle_done(db, wf, task, await pull_requests_of_task(db, task_id))


async def settle_done(db: AsyncSession, wf, task: Task, rows: list[TaskPullRequest]) -> bool:
    """A workflow waiting on human code review follows its tracked pull requests: one closed escalates
    pr_closed (back_merge_pr_closed for the back-merge one); all of them merged finishes it (a production fix has two). An untracked one waits for a person.
    True when it acted. The caller holds the workflow lock."""
    from app.workflow import engine, finish  # local: the workflow imports this module
    from app.workflow.models import Needs, WorkflowStatus

    if wf.status != WorkflowStatus.waiting_human or wf.needs != Needs.human_code_review:
        return False
    expected = {PR_MAIN} | ({PR_BACK_MERGE} if wf.back_merge_pr_url else set())
    by_kind = {r.kind: r for r in rows if r.kind in expected}
    if any(r.error == "branch_mismatch" for r in by_kind.values()):
        return False
    for kind in sorted(by_kind):
        row = by_kind[kind]
        if row.connection_id is not None and row.state == "closed":
            await engine.record_workflow_event(db, task, None, "pr.closed", {"url": row.url, "kind": row.kind})
            await engine.escalate(db, wf, "back_merge_pr_closed" if kind == PR_BACK_MERGE else "pr_closed")
            return True
    if set(by_kind) != expected or any(r.connection_id is None or r.state != "merged" for r in by_kind.values()):
        return False
    for kind in sorted(by_kind):
        row = by_kind[kind]
        await engine.record_workflow_event(db, task, None, "pr.merged", {"url": row.url})
        await audit.record(db, "git.pr_merged", target_type="task", target_id=task.id, data={"url": row.url})
    await finish.finish_workflow(db, wf, task, None)
    return True


async def pull_requests_of_task(db: AsyncSession, task_id: uuid.UUID) -> list[TaskPullRequest]:
    rows = await db.execute(
        select(TaskPullRequest).where(TaskPullRequest.task_id == task_id).order_by(TaskPullRequest.kind)
    )
    return list(rows.scalars())


async def rows_for_delivery(
    db: AsyncSession, conn: GitConnection, path: str | None, number: int | None, sha: str | None
) -> list[uuid.UUID]:
    """The tracked rows a webhook delivery is about: the same repository and number, or the same head commit."""
    rows = (
        await db.execute(select(TaskPullRequest).where(TaskPullRequest.connection_id == conn.id))
    ).scalars().all()
    out = []
    for row in rows:
        ref = providers.parse_pr_url(row.url, conn)
        if ref is None:
            continue
        if path and number is not None and ref.path == path and ref.number == number or sha and row.head_sha == sha and (path is None or ref.path == path):
            if row.task_id not in out:
                out.append(row.task_id)
    return out
