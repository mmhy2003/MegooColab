"""Admin → Git: the provider connections (ADM-1). Tokens and webhook secrets are write-only."""

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import service as audit
from app.auth.deps import AdminUser
from app.core.crypto import encrypt
from app.core.db import DbSession
from app.git import providers
from app.git.models import GitConnection
from app.git.schemas import (
    GitConnectionIn,
    GitConnectionOut,
    GitConnectionPatch,
    GitConnectionTest,
)

router = APIRouter(prefix="/api/admin/git-connections", tags=["git"])


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
