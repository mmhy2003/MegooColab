"""Bearer tokens on REST: only the allow-listed routes accept them (final review C1)."""

import pytest
from sqlalchemy import select

from app.auth.models import Role, User
from tests.factories import login, make_project, make_user


async def _mint(client, scopes) -> str:
    r = await client.post("/api/tokens", json={"name": "t", "scopes": list(scopes)})
    assert r.status_code == 201, r.text
    return r.json()["secret"]


def _bearer(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


@pytest.mark.parametrize("scopes", [("mcp",), ("runner",), ("mcp", "runner")])
async def test_bearer_rejected_on_admin_route(client, client_factory, db, scopes):
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    secret = await _mint(client, scopes)
    victim = await make_user(db)
    bare = client_factory()
    r = await bare.get("/api/admin/agents", headers=_bearer(secret))
    assert r.status_code == 401 and r.json()["detail"] == "bearer_not_allowed"
    r = await bare.post(f"/api/admin/users/{victim.id}/deactivate", headers=_bearer(secret))
    assert r.status_code == 401
    await db.refresh(victim)
    assert victim.status == "active"


@pytest.mark.parametrize("scopes", [("mcp",), ("runner",)])
async def test_bearer_cannot_set_up_totp_or_change_profile(client, client_factory, db, scopes):
    u = await make_user(db, name="Original")
    await login(client, u)
    secret = await _mint(client, scopes)
    bare = client_factory()
    assert (await bare.post("/api/auth/totp/setup", headers=_bearer(secret))).status_code == 401
    r = await bare.post("/api/auth/totp/enable", json={"code": "123456"}, headers=_bearer(secret))
    assert r.status_code == 401
    r = await bare.patch("/api/auth/me", json={"name": "Hijacked"}, headers=_bearer(secret))
    assert r.status_code == 401
    row = (await db.execute(select(User).where(User.id == u.id).execution_options(populate_existing=True))).scalar_one()
    assert row.name == "Original" and not row.totp_enabled and row.totp_secret_enc is None


async def test_bearer_cannot_delete_project_or_task(client, client_factory, db):
    admin = await make_user(db, role=Role.admin)
    await make_project(client, db, "PAY", admin)
    await login(client, admin)
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "Keep me"})).json()
    secret = await _mint(client, ("mcp", "runner"))
    bare = client_factory()
    assert (await bare.delete(f"/api/tasks/{task['key']}", headers=_bearer(secret))).status_code == 401
    assert (await bare.delete("/api/projects/PAY", headers=_bearer(secret))).status_code == 401
    assert (await client.get(f"/api/tasks/{task['key']}")).status_code == 200
    assert (await client.get("/api/projects/PAY")).status_code == 200


async def test_bearer_ignored_even_with_a_valid_cookie(client, db):
    """A cookie session never rescues a bearer request on a non-allow-listed route."""
    u = await make_user(db)
    await login(client, u)
    secret = await _mint(client, ("mcp",))
    r = await client.get("/api/projects", headers=_bearer(secret))
    assert r.status_code == 401


@pytest.mark.parametrize("scopes", [("mcp",), ("runner",)])
async def test_allow_listed_routes_still_accept_bearer(client, client_factory, db, scopes):
    u = await make_user(db)
    await login(client, u)
    secret = await _mint(client, scopes)
    bare = client_factory()
    r = await bare.get("/api/auth/me", headers=_bearer(secret))
    assert r.status_code == 200 and r.json()["user"]["id"] == str(u.id)
    r = await bare.get("/api/tokens/self", headers=_bearer(secret))
    assert r.status_code == 200 and r.json()["scopes"] == list(scopes)
