"""Provider webhooks (GIT-3): signed deliveries only ever trigger a refresh from the API."""

import hashlib
import hmac
import json
import uuid

from sqlalchemy import select

from app.core.crypto import encrypt
from app.core.db import SessionLocal
from app.git.models import GitConnection, TaskPullRequest
from app.jobs.models import Job
from app.projects.models import Project
from app.tasks.models import Task
from tests.factories import make_project, make_user

SECRET = "hook-secret"


def _sig(body: bytes, secret=SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _world(client, db):
    """PAY with three tracked rows: github acme/pay #7, gitea o/r #5, gitlab grp/sub/pay !3."""
    await make_project(client, db, "PAY", await make_user(db))
    project = (await db.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
    conns = {}
    for kind, base, secret in (("github", "https://git.acme.io", SECRET), ("gitea", "https://tea.acme.io", SECRET),
                               ("gitlab", "https://lab.acme.io", SECRET), ("github", "https://nosecret.io", None)):
        c = GitConnection(name=f"{kind}-{base}", kind=kind, base_url=base, token_enc=encrypt("t"),
                          webhook_secret_enc=encrypt(secret) if secret else None)
        db.add(c)
        conns[base] = c
    await db.flush()
    col = (await db.execute(select(Task.column_id).limit(1))).scalar()  # any column of the project
    from app.projects.models import BoardColumn

    col = (await db.execute(select(BoardColumn.id).where(BoardColumn.project_id == project.id).limit(1))).scalar()
    rows = {}
    for n, (base, url) in enumerate((("https://git.acme.io", "https://git.acme.io/acme/pay/pull/7"),
                                      ("https://git.acme.io", "https://git.acme.io/acme/other/pull/7"),
                                      ("https://tea.acme.io", "https://tea.acme.io/o/r/pulls/5"),
                                      ("https://lab.acme.io", "https://lab.acme.io/grp/sub/pay/-/merge_requests/3"))):
        t = Task(project_id=project.id, number=n + 1, type="task", title=f"t{n}", column_id=col, position=float(n))
        db.add(t)
        await db.flush()
        db.add(TaskPullRequest(task_id=t.id, url=url, connection_id=conns[base].id, state="open", head_sha=f"sha{n}"))
        rows[url] = t.id
    await db.commit()
    return conns, rows


async def _queued() -> set[str]:
    async with SessionLocal() as s:
        keys = (await s.execute(select(Job.dedupe_key).where(Job.kind == "git.pr_refresh"))).scalars().all()
    return {k.split(":", 1)[1] for k in keys}


async def _post(client, conn, payload, headers):
    body = json.dumps(payload).encode()
    return await client.post(f"/api/git/webhooks/{conn.id}", content=body,
                             headers={"Content-Type": "application/json", **headers(body)})


async def test_webhook_signature_rejected_and_payload_never_trusted(client, db):
    conns, rows = await _world(client, db)
    gh = conns["https://git.acme.io"]
    payload = {"action": "closed", "pull_request": {"number": 7, "merged": True, "state": "closed"},
               "repository": {"full_name": "acme/pay"}}
    assert (await _post(client, gh, payload, lambda b: {})).status_code == 401
    assert (await _post(client, gh, payload, lambda b: {"X-Hub-Signature-256": _sig(b, "wrong")})).status_code == 401
    assert (await _post(client, gh, payload, lambda b: {"X-Hub-Signature-256": _sig(b)[7:]})).status_code == 401
    lab = conns["https://lab.acme.io"]
    assert (await _post(client, lab, {"object_kind": "merge_request"}, lambda b: {"X-Gitlab-Token": "nope"})).status_code == 401
    nosecret = conns["https://nosecret.io"]
    assert (await _post(client, nosecret, payload, lambda b: {"X-Hub-Signature-256": _sig(b)})).status_code == 404
    assert (await client.post(f"/api/git/webhooks/{uuid.uuid4()}", content=b"{}")).status_code == 404
    big = b"{" + b" " * (1024 * 1024 + 1) + b"}"
    r = await client.post(f"/api/git/webhooks/{gh.id}", content=big, headers={"X-Hub-Signature-256": _sig(big)})
    assert r.status_code == 413
    assert await _queued() == set()

    r = await _post(client, gh, payload, lambda b: {"X-Hub-Signature-256": _sig(b), "X-GitHub-Event": "pull_request"})
    assert r.status_code == 204
    assert await _queued() == {str(rows["https://git.acme.io/acme/pay/pull/7"])}
    async with SessionLocal() as s:  # the payload's "merged" changed nothing: only a refresh was queued
        row = await s.get(TaskPullRequest, rows["https://git.acme.io/acme/pay/pull/7"])
        assert row.state == "open"


async def test_webhook_refreshes_matching_rows_only(client, db):
    conns, rows = await _world(client, db)
    tea = conns["https://tea.acme.io"]
    r = await _post(client, tea, {"pull_request": {"number": 5}, "repository": {"full_name": "o/r"}},
                    lambda b: {"X-Gitea-Signature": "ignored", "X-Hub-Signature-256": _sig(b)})
    assert r.status_code == 204
    lab = conns["https://lab.acme.io"]
    r = await _post(client, lab, {"object_kind": "merge_request", "object_attributes": {"iid": 3},
                                  "project": {"path_with_namespace": "grp/sub/pay"}}, lambda b: {"X-Gitlab-Token": SECRET})
    assert r.status_code == 204
    gh = conns["https://git.acme.io"]
    r = await _post(client, gh, {"state": "success", "sha": "sha1", "repository": {"full_name": "acme/other"}},
                    lambda b: {"X-Hub-Signature-256": _sig(b), "X-GitHub-Event": "status"})
    assert r.status_code == 204
    r = await _post(client, gh, {"pull_request": {"number": 99}, "repository": {"full_name": "acme/pay"}},
                    lambda b: {"X-Hub-Signature-256": _sig(b)})
    assert r.status_code == 204  # no such tracked PR: accepted, nothing queued
    assert await _queued() == {str(rows["https://tea.acme.io/o/r/pulls/5"]),
                               str(rows["https://lab.acme.io/grp/sub/pay/-/merge_requests/3"]),
                               str(rows["https://git.acme.io/acme/other/pull/7"])}
    r = await _post(client, gh, ["not", "an", "object"], lambda b: {"X-Hub-Signature-256": _sig(b)})
    assert r.status_code == 204
    r = await client.post(f"/api/git/webhooks/{gh.id}", content=b"not json", headers={"X-Hub-Signature-256": _sig(b"not json")})
    assert r.status_code == 400
