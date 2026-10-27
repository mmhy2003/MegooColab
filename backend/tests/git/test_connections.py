"""Git provider connections (ADM-1, GIT-1): admin CRUD, the test endpoint, and repository links."""

import logging

import httpx
import pytest
from sqlalchemy import select, text

from app.audit.models import AuditLog
from app.auth.models import Role
from app.git import providers
from tests.factories import login, make_project, make_user

TOKEN = "ghp_SuperSecretToken123456"
SECRET = "hook-secret-xyz"


async def _admin(client, db):
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    return admin


async def _create(client, **kw):
    body = {"name": "GitHub", "kind": "github", "base_url": "https://github.com", "token": TOKEN,
            "webhook_secret": SECRET, **kw}
    return await client.post("/api/admin/git-connections", json=body)


@pytest.fixture
def fake_github(monkeypatch):
    """Every provider call goes to a mock GitHub that knows the token."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"message": "Bad credentials"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "megoo-bot"})
        return httpx.Response(404, json={"message": "Not Found"})

    monkeypatch.setattr(providers, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_admin_crud_and_test_endpoint(client, client_factory, db, fake_github):
    await _admin(client, db)
    r = await _create(client)
    assert r.status_code == 201, r.text
    conn = r.json()
    assert conn == {"id": conn["id"], "name": "GitHub", "kind": "github", "base_url": "https://github.com",
                    "token_set": True, "webhook_secret_set": True}
    assert (await _create(client)).status_code == 409 and (await _create(client)).json()["detail"] == "git_connection_name_taken"
    for bad in ("https://user:pw@github.com", "https://github.com/?x=1", "ftp://github.com", "github.com", "https://"):
        assert (await _create(client, name=f"n{bad}", base_url=bad)).status_code == 422, bad
    r = await _create(client, name="Gitea", kind="gitea", base_url="http://gitea.local:3000/", webhook_secret="")
    assert r.json()["base_url"] == "http://gitea.local:3000" and r.json()["webhook_secret_set"] is False

    r = await client.post(f"/api/admin/git-connections/{conn['id']}/test")
    assert r.json() == {"ok": True, "login": "megoo-bot", "error": None}
    r = await client.patch(f"/api/admin/git-connections/{conn['id']}", json={"token": "wrong", "name": "GitHub.com"})
    assert r.status_code == 200 and r.json()["name"] == "GitHub.com" and r.json()["token_set"] is True
    r = await client.post(f"/api/admin/git-connections/{conn['id']}/test")
    assert r.json() == {"ok": False, "login": None, "error": "unauthorized"}
    r = await client.patch(f"/api/admin/git-connections/{conn['id']}", json={"webhook_secret": ""})
    assert r.json()["webhook_secret_set"] is False
    assert [c["name"] for c in (await client.get("/api/admin/git-connections")).json()] == ["GitHub.com", "Gitea"]
    assert (await client.delete(f"/api/admin/git-connections/{conn['id']}")).status_code == 204
    actions = (await db.execute(select(AuditLog.action).where(AuditLog.action.like("git.connection.%")))).scalars().all()
    assert sorted(set(actions)) == ["git.connection.created", "git.connection.deleted", "git.connection.updated"]

    member = await make_user(db)
    m = client_factory()
    await login(m, member)
    assert (await m.get("/api/admin/git-connections")).status_code == 403
    assert (await _create(m, name="Mine")).status_code == 403


async def test_token_never_returned_or_logged(client, db, fake_github, caplog):
    caplog.set_level(logging.DEBUG)
    await _admin(client, db)
    conn = (await _create(client)).json()
    stored = (await db.execute(text("SELECT token_enc, webhook_secret_enc FROM git_connections"))).one()
    assert TOKEN not in stored[0] and SECRET not in stored[1]
    await client.patch(f"/api/admin/git-connections/{conn['id']}", json={"token": "wrong-token-value"})
    texts = [
        (await client.get("/api/admin/git-connections")).text,
        (await client.post(f"/api/admin/git-connections/{conn['id']}/test")).text,
    ]
    audits = (await db.execute(select(AuditLog.data).where(AuditLog.action.like("git.%")))).scalars().all()
    for blob in [*texts, str(audits), caplog.text]:
        assert TOKEN not in blob and SECRET not in blob and "wrong-token-value" not in blob


async def test_repository_connection_link(client, client_factory, db):
    await _admin(client, db)
    conn = (await _create(client)).json()
    manager_client = client_factory()
    await make_project(manager_client, db, "PAY")
    r = await manager_client.post("/api/projects/PAY/repositories",
                                  json={"name": "pay", "url": "https://github.com/acme/pay", "provider": "github",
                                        "connection_id": conn["id"]})
    assert r.status_code == 201, r.text
    repo = r.json()
    assert repo["connection"] == {"id": conn["id"], "name": "GitHub"}
    r = await manager_client.post("/api/projects/PAY/repositories",
                                  json={"name": "x", "url": "https://github.com/acme/x", "provider": "github",
                                        "connection_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 422 and r.json()["detail"] == "git_connection_not_found"
    r = await manager_client.patch(f"/api/projects/PAY/repositories/{repo['id']}", json={"connection_id": None})
    assert r.json()["connection"] is None
    await manager_client.patch(f"/api/projects/PAY/repositories/{repo['id']}", json={"connection_id": conn["id"]})
    await client.delete(f"/api/admin/git-connections/{conn['id']}")
    [listed] = (await manager_client.get("/api/projects/PAY/repositories")).json()
    assert listed["connection"] is None
