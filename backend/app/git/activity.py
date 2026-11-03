"""Pull request and branch events on the task's Activity (piece 2). Each event from a delivery finds its task (the
task's `megoo/<KEY>` branch, a pull request seen opened from it, or a tracked one), names who acted (the agent of a
run on the task for its pushes and new pull requests, else the host's person) and becomes one `git.*` entry; a
review's line comments are folded into the review's entry."""

import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.core.events import Event, publish
from app.git import agent_review, providers, send_back
from app.git.events import GitEvent
from app.git.models import GitConnection, GitKind, GitPrLink, TaskPullRequest
from app.projects.models import Project, ProjectRepository
from app.tasks.models import Task, TaskEvent

log = logging.getLogger(__name__)

AGENT_WINDOW = timedelta(minutes=5)
_TASK_BRANCH = re.compile(r"^megoo/([A-Za-z][A-Za-z0-9]{1,9}-\d{1,9})(?:-|$)")
_PR_KINDS = ("git.pr_opened", "git.pr_merged", "git.pr_closed")


def task_key_of(branch: str | None) -> str | None:
    """The task a `megoo/<KEY>…` branch belongs to (upper-cased key), or None."""
    m = _TASK_BRANCH.match(branch or "")
    return m.group(1).upper() if m else None


async def agent_actor(db: AsyncSession, task: Task) -> dict | None:
    """The agent of the task's latest run that is running, or finished within AGENT_WINDOW: agents push and open
    pull requests with the developer's own account, so the host can't say it was them."""
    since = datetime.now(UTC) - AGENT_WINDOW
    row = (
        await db.execute(
            select(Agent.id, Agent.name)
            .join(AgentRun, AgentRun.agent_id == Agent.id)
            .where(
                AgentRun.task_id == task.id,
                AgentRun.started_at.is_not(None),
                ((AgentRun.status == RunStatus.running) & AgentRun.finished_at.is_(None)) | (AgentRun.finished_at >= since),
            )
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        )
    ).first()
    return None if row is None else {"kind": "agent", "agent_id": str(row.id), "name": row.name}


async def _task_by_key(db: AsyncSession, conn: GitConnection, path: str, key: str) -> Task | None:
    project_key, number = key.rsplit("-", 1)
    project = (await db.execute(select(Project).where(Project.key == project_key))).scalar_one_or_none()
    if project is None:
        return None
    repos = (
        await db.execute(
            select(ProjectRepository.url).where(
                ProjectRepository.project_id == project.id, ProjectRepository.connection_id == conn.id
            )
        )
    ).scalars()
    if not any((providers.repo_path(url) or "").lower() == path.lower() for url in repos):
        return None
    return (
        await db.execute(select(Task).where(Task.project_id == project.id, Task.number == int(number)))
    ).scalar_one_or_none()


async def _tracked(db: AsyncSession, conn: GitConnection, path: str, number: int) -> TaskPullRequest | None:
    rows = (await db.execute(select(TaskPullRequest).where(TaskPullRequest.connection_id == conn.id))).scalars()
    for row in rows:
        ref = providers.parse_pr_url(row.url, conn)
        if ref is not None and ref.path.lower() == path.lower() and ref.number == number:
            return row
    return None


async def _review_entry(db: AsyncSession, task: Task, review_id: str | None) -> TaskEvent | None:
    if not review_id:
        return None
    return (
        await db.execute(
            select(TaskEvent).where(
                TaskEvent.task_id == task.id,
                TaskEvent.kind == "git.reviewed",
                TaskEvent.data["review_id"].astext == review_id,
            )
        )
    ).scalars().first()


async def record(db: AsyncSession, conn: GitConnection, events: list[GitEvent], *, repo: ProjectRepository | None) -> int:
    """Writes each event its task's Activity shows; returns how many entries were written or updated. Through a
    repository's own address, only that repository's events reach only its project's tasks (the same repository in
    two projects has two webhooks, each delivering every event)."""
    # local: the workflow imports the git modules
    from app.workflow.engine import lock_task_row, record_workflow_event

    own = providers.repo_path(repo.url) if repo is not None else None
    written = 0
    for ev in events:
        if own is not None and ev.path.lower() != own.lower():
            continue
        if ev.data.get("agent_review"):  # the agent reviewer's own post: its report is on the task already
            continue
        link = None if ev.number is None else await db.get(GitPrLink, (conn.id, ev.path, ev.number))
        task, by_branch = None, False
        if key := task_key_of(ev.branch):
            task = await _task_by_key(db, conn, ev.path, key)
            by_branch = task is not None
        tracked = None
        if task is None and link is not None:
            task = await db.get(Task, link.task_id)
        if task is None and ev.number is not None:
            tracked = await _tracked(db, conn, ev.path, ev.number)
            task = None if tracked is None else await db.get(Task, tracked.task_id)
        if task is None or (repo is not None and task.project_id != repo.project_id):
            continue
        # one delivery at a time per task: a review and its line comments arrive together
        if not await lock_task_row(db, task.id):
            continue
        link = None if ev.number is None else (
            await db.execute(select(GitPrLink).where(
                GitPrLink.connection_id == conn.id, GitPrLink.path == ev.path, GitPrLink.number == ev.number,
            ).execution_options(populate_existing=True))
        ).scalar_one_or_none()

        pr = None
        if ev.number is not None:
            url = ev.data.get("url") if ev.kind in _PR_KINDS else None
            if url is None and link is not None and link.task_id == task.id:
                url = link.url
            if url is None:
                tracked = tracked or await _tracked(db, conn, ev.path, ev.number)
                url = tracked.url if tracked is not None else None
            pr = {"number": ev.number, "url": url}
            closing = ev.kind in ("git.pr_merged", "git.pr_closed")
            if ev.kind == "git.pr_opened" or (by_branch and link is None):
                values = {"task_id": task.id, "open": not closing, "url": (link.url if link else None) or pr["url"],
                          "head_branch": ev.branch or (link.head_branch if link else None)}
                await db.execute(
                    pg_insert(GitPrLink)
                    .values(connection_id=conn.id, path=ev.path, number=ev.number, **values)
                    .on_conflict_do_update(index_elements=["connection_id", "path", "number"], set_=values)
                )
            elif closing and link is not None:
                link.open = False
            await db.flush()
        elif ev.kind == "git.pushed":
            opened = (
                await db.execute(
                    select(GitPrLink).where(
                        GitPrLink.connection_id == conn.id, GitPrLink.path == ev.path,
                        GitPrLink.head_branch == ev.branch, GitPrLink.open.is_(True),
                    )
                )
            ).scalars().first()
            pr = None if opened is None else {"number": opened.number, "url": opened.url}

        actor = {"kind": "person", **ev.actor}
        if ev.kind in ("git.pushed", "git.pr_opened") and (agent := await agent_actor(db, task)) is not None:
            actor = {**agent, "login": ev.actor.get("login")}
        base = {"host": GitKind(conn.kind).value, "actor": actor, "pr": pr}

        trigger = None
        if ev.kind in ("git.reviewed", "git.review_comment"):
            review = await _fold_review(db, task, ev, base)
            if review is not None:  # its verdict just became "changes requested"
                first = review.get("first") or {}
                where = f"{first['file']}:{first['line']}" if first.get("file") and first.get("line") else first.get("file")
                trigger = send_back.Trigger(
                    kind="review", pr_url=(pr or {}).get("url"), pr_number=ev.number, by=actor["name"],
                    excerpt=review.get("excerpt") or first.get("excerpt") or "", where=where,
                    association=ev.data.get("association"), host=base["host"])
        elif ev.kind == "git.pushed":
            await record_workflow_event(db, task, None, ev.kind, {**base, "branch": ev.branch, **ev.data})
        elif ev.kind == "git.pr_opened":
            details = {k: v for k, v in ev.data.items() if k != "url"}
            await record_workflow_event(db, task, None, ev.kind, {**base, "branch": ev.branch, **details})
        elif ev.kind == "git.commented":
            await record_workflow_event(db, task, None, ev.kind, {**base, **ev.data})
            if send_back.is_fix_comment(ev.data.get("excerpt")):
                trigger = send_back.Trigger(
                    kind="fix_comment", pr_url=(pr or {}).get("url"), pr_number=ev.number, by=actor["name"],
                    excerpt=ev.data.get("excerpt") or "", where=None, association=ev.data.get("association"),
                    host=base["host"])
        else:
            await record_workflow_event(db, task, None, ev.kind, base)
        written += 1
        if trigger is not None:
            try:  # sending back never costs the event its Activity entry
                async with db.begin_nested():
                    await send_back.consider(db, task, trigger)
            except Exception:
                log.exception("git: sending task %s back failed", task.id)
    return written


async def _fold_review(db: AsyncSession, task: Task, ev: GitEvent, base: dict) -> dict | None:
    """One entry per review: its line comments add to it, whichever arrives first. Returns the entry's data when
    its verdict has just become "changes requested" (a send-back trigger), else None."""
    # local: the workflow imports the git modules
    from app.workflow.engine import record_workflow_event

    entry = await _review_entry(db, task, ev.data.get("review_id"))
    if ev.kind == "git.review_comment":
        first = {k: ev.data.get(k) for k in ("file", "line", "excerpt", "url")}
        if entry is None:
            await record_workflow_event(db, task, None, "git.reviewed", {
                **base, "review_id": ev.data["review_id"], "verdict": "commented", "excerpt": "", "url": None,
                "comments": 1, "first": first})
            return None
        data = dict(entry.data)
        data["comments"] = int(data.get("comments") or 0) + 1
        data["first"] = data.get("first") or first
    else:
        if entry is None:
            data = {**base, **ev.data, "comments": 0, "first": None}
            await record_workflow_event(db, task, None, "git.reviewed", data)
            return data if data["verdict"] == "changes_requested" else None
        became = entry.data.get("verdict") != "changes_requested" and ev.data["verdict"] == "changes_requested"
        data = {**entry.data, "verdict": ev.data["verdict"], "excerpt": ev.data["excerpt"], "url": ev.data["url"],
                "actor": base["actor"]}
    entry.data = data  # a new dict, so the JSONB change is saved
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
    return data if ev.kind == "git.reviewed" and became else None


# imported for its effect: the review run's end and its escalations get their handlers (piece 4)
_REGISTERED = agent_review
