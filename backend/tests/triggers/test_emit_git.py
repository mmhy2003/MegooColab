"""A pull request merged into the repository's default branch, matching no task, writes pending firings."""

import uuid

import pytest
from sqlalchemy import inspect, select

from app.core.crypto import encrypt
from app.git import activity
from app.git.events import parse_delivery
from app.git.models import GitConnection, GitKind, GitPrLink
from app.projects.models import BoardColumn, ProjectRepository
from app.tasks.models import Task
from app.triggers.models import FiringStatus, Trigger, TriggerFiring
from tests.triggers.helpers import make_trigger

BASES = {GitKind.github: "https://github.com", GitKind.gitea: "https://tea.example", GitKind.gitlab: "https://lab.example"}


async def _firings(db, trigger: Trigger) -> list[TriggerFiring]:
    [trigger_id] = inspect(trigger).identity  # no load: the trigger may be expired
    db.expire_all()
    return list((await db.execute(select(TriggerFiring).where(TriggerFiring.trigger_id == trigger_id))).scalars())


async def _repo(db, w, kind: GitKind = GitKind.github) -> tuple[GitConnection, ProjectRepository]:
    """acme/pay of PAY on a connection of this kind, with its own webhook secret; default branch main."""
    base = BASES[kind]
    conn = GitConnection(name=kind.value, kind=kind.value, base_url=base, token_enc=encrypt("t"))
    db.add(conn)
    await db.flush()
    repo = ProjectRepository(project_id=uuid.UUID(w.project["id"]), name="acme/pay", url=f"{base}/acme/pay",
                             provider=kind.value, connection_id=conn.id, webhook_secret_enc=encrypt("s"))
    db.add(repo)
    await db.commit()
    return conn, repo


def _merged(kind: GitKind, *, head: str = "fix-typo", base: str = "main", number: int = 5) -> list:
    """A merged pull request's delivery, as the provider sends it."""
    url = f"{BASES[kind]}/acme/pay/pull/{number}"
    if kind == GitKind.gitlab:
        attrs = {"iid": number, "url": url, "title": "Fix the typo", "source_branch": head, "target_branch": base,
                 "action": "merge"}
        payload = {"object_attributes": attrs, "project": {"path_with_namespace": "acme/pay"},
                   "user": {"name": "Mo Y", "username": "mo"}}
        return parse_delivery(kind, {"x-gitlab-event": "Merge Request Hook"}, payload)
    pr = {"number": number, "html_url": url, "title": "Fix the typo", "head": {"ref": head}, "base": {"ref": base},
          "merged": True}
    payload = {"action": "closed", "pull_request": pr, "repository": {"full_name": "acme/pay"},
               "sender": {"login": "mo", "full_name": "Mo Y"}}
    header = "x-gitea-event" if kind == GitKind.gitea else "x-github-event"
    return parse_delivery(kind, {header: "pull_request"}, payload)


@pytest.mark.parametrize("kind", [GitKind.github, GitKind.gitea, GitKind.gitlab])
async def test_untracked_merge_into_default_branch_fires(db, world, kind):
    trigger = await make_trigger(db, world, "pr_merged")
    conn, repo = await _repo(db, world, kind)
    await activity.record(db, conn, _merged(kind), repo=repo)
    await db.commit()
    [firing] = await _firings(db, trigger)
    assert firing.status == FiringStatus.pending and firing.event == "pr_merged"
    url = f"{BASES[kind]}/acme/pay/pull/5"
    assert firing.subject == {"kind": "pr", "label": "#5", "title": "Fix the typo", "link": url,
                              "note": "merged into main"}
    actor = "mo" if kind == GitKind.github else "Mo Y"
    assert f'Pull request #5 "Fix the typo" was merged into main of repository acme/pay by {actor}.' in firing.what
    assert "Branch: fix-typo" in firing.what and f"URL: {url}" in firing.what


async def test_merge_into_another_branch_or_of_a_tracked_pr_fires_nothing(db, world):
    trigger = await make_trigger(db, world, "pr_merged")
    conn, repo = await _repo(db, world)
    col = await db.scalar(select(BoardColumn.id).where(BoardColumn.project_id == repo.project_id).limit(1))
    task = Task(project_id=repo.project_id, number=1, type="task", title="Retries", column_id=col, position=1.0)
    db.add(task)
    await db.flush()
    db.add(GitPrLink(connection_id=conn.id, path="acme/pay", number=7, task_id=task.id, url=None, head_branch="x"))
    await db.commit()

    await activity.record(db, conn, _merged(GitKind.github, base="develop"), repo=repo)
    await activity.record(db, conn, _merged(GitKind.github, head="megoo/PAY-1-retries", number=6), repo=repo)
    await activity.record(db, conn, _merged(GitKind.github, head="renamed", number=7), repo=repo)
    await db.commit()
    assert await _firings(db, trigger) == []


async def test_shared_connection_address_fires_nothing(db, world):
    trigger = await make_trigger(db, world, "pr_merged")
    conn, _ = await _repo(db, world)
    await activity.record(db, conn, _merged(GitKind.github), repo=None)
    await db.commit()
    assert await _firings(db, trigger) == []
