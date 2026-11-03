"""A repository's own webhook (piece 1): its own address and secret, its status, and no repeats."""

import hashlib
import hmac
import json
import uuid

from sqlalchemy import select, update

from app.core.crypto import encrypt
from app.core.db import SessionLocal
from app.git.models import GitConnection, TaskPullRequest
from app.jobs.models import Job, JobStatus
from app.projects.models import BoardColumn, Project, ProjectRepository
from app.tasks.models import Task
from tests.factories import make_project

REPO_SECRET = "repo-secret"
SHARED = "shared-secret"
PAYLOAD = {"action": "closed", "pull_request": {"number": 7}, "repository": {"full_name": "acme/pay"}}


def _sig(body: bytes, secret: str = REPO_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _world(client, db, kind: str = "github"):
    """PAY with repository acme/pay on a connection (which still has an old shared secret) and a tracked PR #7."""
    await make_project(client, db, "PAY")
    project = (await db.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
    base = "https://lab.acme.io" if kind == "gitlab" else "https://github.com"
    conn = GitConnection(name="Host", kind=kind, base_url=base, token_enc=encrypt("t"), webhook_secret_enc=encrypt(SHARED))
    db.add(conn)
    await db.flush()
    repo = ProjectRepository(project_id=project.id, name="acme/pay", url=f"{base}/acme/pay", provider=kind,
                             connection_id=conn.id, webhook_secret_enc=encrypt(REPO_SECRET))
    col = (await db.execute(select(BoardColumn.id).where(BoardColumn.project_id == project.id).limit(1))).scalar()
    task = Task(project_id=project.id, number=1, type="task", title="t", column_id=col, position=1.0)
    db.add_all([repo, task])
    await db.flush()
    pr_url = f"{base}/acme/pay/-/merge_requests/7" if kind == "gitlab" else f"{base}/acme/pay/pull/7"
    db.add(TaskPullRequest(task_id=task.id, url=pr_url, connection_id=conn.id, state="open", head_sha="sha0"))
    await db.commit()
    return conn, repo, task


async def _post(client, path: str, payload=PAYLOAD, headers=None, secret: str = REPO_SECRET, delivery: str | None = None):
    body = json.dumps(payload).encode()
    h = {"Content-Type": "application/json", "X-Hub-Signature-256": _sig(body, secret), **(headers or {})}
    if delivery:
        h["X-GitHub-Delivery"] = delivery
    return await client.post(path, content=body, headers=h)


async def _repo(repo_id) -> ProjectRepository:
    async with SessionLocal() as s:
        return await s.get(ProjectRepository, repo_id)


async def _queued() -> int:
    async with SessionLocal() as s:
        return len((await s.execute(
            select(Job.id).where(Job.kind == "git.pr_refresh", Job.status == JobStatus.queued)
        )).scalars().all())


async def _status(client, repo) -> dict:
    rows = (await client.get("/api/projects/PAY/repositories")).json()
    return next(r for r in rows if r["id"] == str(repo.id))


async def test_a_signed_delivery_marks_working_and_refreshes(client, db):
    _, repo, _ = await _world(client, db)
    assert (await _status(client, repo))["webhook_status"] == "not_set_up"
    r = await _post(client, f"/api/git/webhooks/repos/{repo.id}")
    assert r.status_code == 204, r.text
    out = await _status(client, repo)
    assert out["webhook_status"] == "working" and out["webhook_last_at"]
    assert await _queued() == 1


async def test_bad_signature_marks_failing_until_a_good_one(client, db):
    _, repo, _ = await _world(client, db)
    assert (await _post(client, f"/api/git/webhooks/repos/{repo.id}", secret="old")).status_code == 401
    assert (await _status(client, repo))["webhook_status"] == "failing"
    assert (await _post(client, f"/api/git/webhooks/repos/{repo.id}")).status_code == 204
    assert (await _status(client, repo))["webhook_status"] == "working"


async def test_gitlab_uses_its_token_header(client, db):
    _, repo, _ = await _world(client, db, "gitlab")
    payload = {"object_kind": "merge_request", "object_attributes": {"iid": 7}, "project": {"path_with_namespace": "acme/pay"}}
    body = json.dumps(payload).encode()
    path = f"/api/git/webhooks/repos/{repo.id}"
    assert (await client.post(path, content=body, headers={"X-Gitlab-Token": "nope"})).status_code == 401
    assert (await client.post(path, content=body, headers={"X-Gitlab-Token": REPO_SECRET})).status_code == 204
    assert await _queued() == 1


async def test_a_repeated_delivery_is_ignored(client, db):
    _, repo, _ = await _world(client, db)
    path = f"/api/git/webhooks/repos/{repo.id}"
    assert (await _post(client, path, delivery="d-1")).status_code == 204
    assert await _queued() == 1
    async with SessionLocal() as s:  # the refresh ran
        await s.execute(update(Job).values(status=JobStatus.done))
        await s.commit()
    assert (await _post(client, path, delivery="d-1")).status_code == 204  # the host retried: nothing new
    assert await _queued() == 0
    assert (await _post(client, path, delivery="d-2")).status_code == 204
    assert await _queued() == 1


async def test_unknown_or_secretless_repository_is_404(client, db):
    _, repo, _ = await _world(client, db)
    assert (await _post(client, f"/api/git/webhooks/repos/{uuid.uuid4()}")).status_code == 404
    async with SessionLocal() as s:
        await s.execute(update(ProjectRepository).values(webhook_secret_enc=None))
        await s.commit()
    assert (await _post(client, f"/api/git/webhooks/repos/{repo.id}")).status_code == 404


async def test_the_shared_address_still_works_and_counts_for_no_repository(client, db):
    conn, repo, _ = await _world(client, db)
    r = await _post(client, f"/api/git/webhooks/{conn.id}", secret=SHARED)
    assert r.status_code == 204
    assert await _queued() == 1
    assert (await _status(client, repo))["webhook_status"] == "not_set_up"


async def test_the_same_delivery_id_counts_once_per_address(client, db):
    """Two repositories whose webhooks one event fires (the same id at both): each address handles it once."""
    conn, repo, _ = await _world(client, db)
    async with SessionLocal() as s:
        twin = ProjectRepository(project_id=repo.project_id, name="acme/pay-twin", url="https://github.com/acme/pay",
                                 provider="github", connection_id=conn.id, webhook_secret_enc=encrypt(REPO_SECRET))
        s.add(twin)
        await s.commit()
        twin_id = twin.id
    assert (await _post(client, f"/api/git/webhooks/repos/{repo.id}", delivery="d-1")).status_code == 204
    assert await _queued() == 1
    async with SessionLocal() as s:
        await s.execute(update(Job).values(status=JobStatus.done))
        await s.commit()
    assert (await _post(client, f"/api/git/webhooks/repos/{twin_id}", delivery="d-1")).status_code == 204
    assert await _queued() == 1
    assert (await _repo(twin_id)).webhook_last_at is not None


async def test_gitlab_retries_are_matched_by_idempotency_key(client, db):
    """GitLab's event id is shared by every hook one event fires; its Idempotency-Key is what a retry repeats."""
    _, repo, _ = await _world(client, db, "gitlab")
    payload = {"object_kind": "merge_request", "object_attributes": {"iid": 7}, "project": {"path_with_namespace": "acme/pay"}}
    body = json.dumps(payload).encode()
    path = f"/api/git/webhooks/repos/{repo.id}"

    async def send(key: str):
        headers = {"X-Gitlab-Token": REPO_SECRET, "X-Gitlab-Event-UUID": "event-1", "Idempotency-Key": key}
        assert (await client.post(path, content=body, headers=headers)).status_code == 204

    async def settle():
        async with SessionLocal() as s:
            await s.execute(update(Job).values(status=JobStatus.done))
            await s.commit()

    await send("k-1")
    assert await _queued() == 1
    await settle()
    await send("k-2")  # another delivery of the same event: handled
    assert await _queued() == 1
    await settle()
    await send("k-2")  # its retry: ignored
    assert await _queued() == 0
