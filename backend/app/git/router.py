"""Admin → Git: the provider connections (ADM-1), whose tokens and webhook secrets are write-only, and the
providers' webhooks (GIT-3)."""

import hashlib
import hmac
import json
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import service as audit
from app.auth.deps import AdminUser, AuthedUser
from app.core.crypto import decrypt, encrypt
from app.core.db import DbSession
from app.git import providers, service
from app.git.models import GitConnection, GitKind
from app.git.schemas import (
    ConnectionRef,
    GitConnectionIn,
    GitConnectionOut,
    GitConnectionPatch,
    GitConnectionTest,
)
from app.ratelimit import guards
from app.ratelimit.clientip import client_ip

router = APIRouter(prefix="/api/admin/git-connections", tags=["git"])
names_router = APIRouter(prefix="/api/git/connections", tags=["git"])


def _out(c: GitConnection) -> GitConnectionOut:
    return GitConnectionOut(id=c.id, name=c.name, kind=c.kind, base_url=c.base_url, token_set=bool(c.token_enc),
                            webhook_secret_set=bool(c.webhook_secret_enc))


async def _connection(db, connection_id: uuid.UUID) -> GitConnection:
    c = await db.get(GitConnection, connection_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "git_connection_not_found")
    return c


async def _flush_unique(db) -> None:
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "git_connection_name_taken") from None


@router.get("")
async def list_connections(db: DbSession, _admin: AdminUser) -> list[GitConnectionOut]:
    rows = await db.execute(select(GitConnection).order_by(GitConnection.created_at, GitConnection.name))
    return [_out(c) for c in rows.scalars()]


@names_router.get("")
async def connection_names(db: DbSession, _user: AuthedUser) -> list[ConnectionRef]:
    """For linking a project's repositories (a project manager's choice): names only."""
    rows = await db.execute(select(GitConnection.id, GitConnection.name).order_by(GitConnection.name))
    return [ConnectionRef(id=i, name=n) for i, n in rows.all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_connection(body: GitConnectionIn, db: DbSession, admin: AdminUser) -> GitConnectionOut:
    c = GitConnection(name=body.name, kind=body.kind, base_url=body.base_url, token_enc=encrypt(body.token),
                      webhook_secret_enc=encrypt(body.webhook_secret) if body.webhook_secret else None,
                      created_by=admin.id)
    db.add(c)
    await _flush_unique(db)
    await audit.record(db, "git.connection.created", actor_id=admin.id, target_type="git_connection", target_id=c.id,
                       data={"name": c.name, "kind": str(c.kind), "base_url": c.base_url})
    return _out(c)


@router.patch("/{connection_id}")
async def update_connection(
    connection_id: uuid.UUID, body: GitConnectionPatch, db: DbSession, admin: AdminUser
) -> GitConnectionOut:
    c = await _connection(db, connection_id)
    fields = body.model_fields_set
    if body.name is not None:
        c.name = body.name
    if body.base_url is not None:
        c.base_url = body.base_url
    if body.token is not None:
        c.token_enc = encrypt(body.token)
    if "webhook_secret" in fields and body.webhook_secret is not None:
        c.webhook_secret_enc = encrypt(body.webhook_secret) if body.webhook_secret else None
    await _flush_unique(db)
    await audit.record(db, "git.connection.updated", actor_id=admin.id, target_type="git_connection", target_id=c.id,
                       data={"fields": sorted(fields)})  # names only, never the values
    return _out(c)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: uuid.UUID, db: DbSession, admin: AdminUser) -> Response:
    c = await _connection(db, connection_id)
    await db.delete(c)
    await audit.record(db, "git.connection.deleted", actor_id=admin.id, target_type="git_connection",
                       target_id=connection_id, data={"name": c.name})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{connection_id}/test")
async def test_connection(connection_id: uuid.UUID, db: DbSession, _admin: AdminUser) -> GitConnectionTest:
    c = await _connection(db, connection_id)
    try:
        return GitConnectionTest(ok=True, login=await providers.whoami(c))
    except providers.GitProviderError as e:
        return GitConnectionTest(ok=False, error=e.code)


# ---- webhooks (GIT-3) -------------------------------------------------------------------------

webhook_router = APIRouter(prefix="/api/git/webhooks", tags=["git"])
WEBHOOK_MAX_BYTES = 1024 * 1024


async def _body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > WEBHOOK_MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too_large")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > WEBHOOK_MAX_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too_large")
    return body


def _signed(conn: GitConnection, secret: str, request: Request, body: bytes) -> bool:
    """GitHub and Gitea/Forgejo: X-Hub-Signature-256 = sha256=<hex HMAC of the raw body>. GitLab: X-Gitlab-Token."""
    if conn.kind == GitKind.gitlab:
        token = request.headers.get("x-gitlab-token", "")
        return hmac.compare_digest(token.encode(), secret.encode())
    given = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(given.encode(), expected.encode())


def _about(conn: GitConnection, payload: dict) -> tuple[str | None, int | None, str | None]:
    """(repository path, pull request number, head sha) a delivery mentions. Only identity is read from the
    payload, never a state: the state is read from the provider API afterwards."""

    def _int(value) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    if conn.kind == GitKind.gitlab:
        project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
        attrs = payload.get("object_attributes") if isinstance(payload.get("object_attributes"), dict) else {}
        mr = payload.get("merge_request") if isinstance(payload.get("merge_request"), dict) else {}
        number = _int(attrs.get("iid")) if payload.get("object_kind") == "merge_request" else _int(mr.get("iid"))
        path = project.get("path_with_namespace")
        return (path if isinstance(path, str) else None), number, None
    repo = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    path = repo.get("full_name") if isinstance(repo.get("full_name"), str) else None
    pr = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
    number = _int(pr.get("number")) or _int(payload.get("number"))
    if number is None:
        run = payload.get("check_run") or payload.get("check_suite")
        prs = run.get("pull_requests") if isinstance(run, dict) else None
        if isinstance(prs, list) and prs and isinstance(prs[0], dict):
            number = _int(prs[0].get("number"))
    sha = payload.get("sha") if isinstance(payload.get("sha"), str) else None
    return path, number, sha


@webhook_router.post("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def receive_webhook(connection_id: uuid.UUID, request: Request, db: DbSession) -> Response:
    """A provider says something changed. Verified, it only queues refreshes of the pull requests it names.

    Rate limits (Plan 10): a genuine delivery counts against its connection; an unknown connection or a bad
    signature counts against the sender's address, so a forged flood cannot use up a real connection's budget."""
    ip = client_ip(request)
    await guards.check("api_ip", ip, request)
    conn = await db.get(GitConnection, connection_id)
    if conn is None or not conn.webhook_secret_enc:
        await guards.count("api_ip", ip)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    body = await _body(request)
    if not _signed(conn, decrypt(conn.webhook_secret_enc), request, body):
        await guards.count("api_ip", ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_signature")
    await guards.hit("webhook_connection", str(conn.id), request)
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_payload") from None
    if isinstance(payload, dict):
        path, number, sha = _about(conn, payload)
        for task_id in await service.rows_for_delivery(db, conn, path, number, sha):
            await service.queue_refresh(db, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
