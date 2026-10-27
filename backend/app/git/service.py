"""Following a task's pull request (GIT-3, GIT-5) and what it means for the Done stage (WF-6a).

A pull request is tracked only when its URL is on the base URL of a connection linked to one of the task's
project repositories, and names that repository. Its state always comes from the provider API with the
connection's read-only token (webhooks only trigger a refresh). A provider error keeps the last known state and
backs off; it never finishes or escalates anything.

While a workflow waits on `human_code_review`: merged -> finished; closed -> escalation `pr_closed`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.git import providers
from app.git.models import GitConnection, TaskPullRequest
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


async def track_pr(db: AsyncSession, task: Task, url: str) -> TaskPullRequest:
    """The Finish run reported a pull request: (re)start following it. A new report replaces the old one."""
    found = await match_pr(db, task.project_id, url)
    row = await db.get(TaskPullRequest, task.id)
    if row is None:
        row = TaskPullRequest(task_id=task.id)
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


async def refresh_pr(db: AsyncSession, row: TaskPullRequest) -> None:
    """Read the pull request from the provider (outside any lock), then apply what changed."""
    conn = await db.get(GitConnection, row.connection_id) if row.connection_id else None
    ref = providers.parse_pr_url(row.url, conn) if conn is not None else None
    if conn is None or ref is None:
        return
    task_id = row.task_id
    try:
        status = await providers.fetch_pr(conn, ref)
    except providers.GitProviderError as e:
        locked = await _lock_row(db, task_id)
        if locked is not None:
            locked.failures += 1
            locked.error = e.code
            locked.last_checked_at = _now()
            locked.next_check_at = _now() + timedelta(minutes=min(2 ** locked.failures, MAX_BACKOFF_MINUTES))
            await db.flush()
        return
    await apply_status(db, task_id, status)


async def _lock_row(db: AsyncSession, task_id: uuid.UUID) -> TaskPullRequest | None:
    return (
        await db.execute(
            select(TaskPullRequest).where(TaskPullRequest.task_id == task_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def apply_status(db: AsyncSession, task_id: uuid.UUID, status: providers.PrStatus) -> None:
    """Store the provider's view; on a change, record it and move a waiting Done stage on."""
    from app.workflow import engine  # local: the workflow imports this module

    task = await db.get(Task, task_id)
    if task is None:
        return
    wf = await engine.lock_task(db, task)  # the engine's lock order: task, workflow, then our row
    row = await _lock_row(db, task_id)
    if row is None:
        return
    changed = (row.state, row.checks, row.review) != (status.state, status.checks, status.review)
    row.state, row.checks, row.review = status.state, status.checks, status.review
    row.merged_at, row.head_sha = status.merged_at, status.head_sha
    row.error, row.failures = None, 0
    row.last_checked_at = _now()
    row.next_check_at = _now() + timedelta(seconds=POLL_SECONDS)
    await db.flush()
    if not changed:
        return
    await engine.record_workflow_event(db, task, None, "pr.status",
                                       {"state": status.state, "checks": status.checks, "review": status.review})
    if wf is not None:
        await settle_done(db, wf, task, row)


async def settle_done(db: AsyncSession, wf, task: Task, row: TaskPullRequest | None) -> bool:
    """A workflow waiting on human code review follows its tracked pull request: merged finishes it, closed
    escalates pr_closed. True when it acted. The caller holds the workflow lock."""
    from app.workflow import engine, finish  # local: the workflow imports this module
    from app.workflow.models import Needs, WorkflowStatus

    if row is None or row.connection_id is None or wf.status != WorkflowStatus.waiting_human:
        return False
    if wf.needs != Needs.human_code_review:
        return False
    if row.state == "merged":
        await engine.record_workflow_event(db, task, None, "pr.merged", {"url": row.url})
        await audit.record(db, "git.pr_merged", target_type="task", target_id=task.id, data={"url": row.url})
        await finish.finish_workflow(db, wf, task, None)
        return True
    if row.state == "closed":
        await engine.escalate(db, wf, "pr_closed")
        return True
    return False


async def pull_request_of(db: AsyncSession, task_id: uuid.UUID) -> TaskPullRequest | None:
    return await db.get(TaskPullRequest, task_id)


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
            out.append(row.task_id)
    return out
