from datetime import timedelta

from sqlalchemy import select

from app.auth.models import PersonalAccessToken, Role, TokenScope
from app.auth.service import now
from app.auth.tokens import resolve_bearer
from app.core.security import hash_token
from tests.factories import login, make_user


async def _mint(client, scopes=("mcp",), **extra) -> dict:
    r = await client.post("/api/tokens", json={"name": "t", "scopes": list(scopes), **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _bearer(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


async def test_create_token_shows_secret_once_and_stores_hash(client, db):
    u = await make_user(db)
    await login(client, u)
    r = await client.post("/api/tokens", json={"name": "laptop", "scopes": ["runner", "mcp"]})
    assert r.status_code == 201
    secret = r.json()["secret"]
    assert secret.startswith("mgc_") and r.json()["token"]["prefix"] == secret[:8]
    rows = (await db.execute(select(PersonalAccessToken.token_hash))).scalars().all()
    assert secret not in rows and hash_token(secret) in rows
    assert "secret" not in (await client.get("/api/tokens")).json()[0]


async def test_bearer_token_authenticates_and_ignores_cookies(client_factory, db):
    a = await make_user(db)
    b = await make_user(db)
    ca = client_factory()
    await login(ca, a)
    secret = (await _mint(ca))["secret"]
    cb = client_factory()
    await login(cb, b)  # cb has b's cookie...
    r = await cb.get("/api/auth/me", headers=_bearer(secret))
    assert r.json()["user"]["id"] == str(a.id)  # ...but the bearer wins
    r = await cb.get("/api/auth/me", headers={"Authorization": "Bearer mgc_bogus"})
    assert r.status_code == 401  # bad bearer never falls back to the cookie


async def test_revoked_token_rejected(client, client_factory, db):
    u = await make_user(db)
    await login(client, u)
    made = await _mint(client)
    anon = client_factory()
    assert (await anon.get("/api/auth/me", headers=_bearer(made["secret"]))).status_code == 200
    assert (await client.delete(f"/api/tokens/{made['token']['id']}")).status_code == 204
    assert (await anon.get("/api/auth/me", headers=_bearer(made["secret"]))).status_code == 401
    assert (await client.get("/api/tokens")).json()[0]["revoked_at"] is not None


async def test_expired_token_rejected(client, client_factory, db):
    u = await make_user(db)
    await login(client, u)
    made = await _mint(client, expires_in_days=7)
    assert made["token"]["expires_at"] is not None
    row = await db.get(PersonalAccessToken, made["token"]["id"])
    row.expires_at = now() - timedelta(seconds=1)
    await db.commit()
    anon = client_factory()
    assert (await anon.get("/api/auth/me", headers=_bearer(made["secret"]))).status_code == 401


async def test_scope_enforced(client, db):
    u = await make_user(db)
    await login(client, u)
    secret = (await _mint(client, scopes=["mcp"]))["secret"]
    assert await resolve_bearer(db, secret, scope=TokenScope.runner) is None
    assert await resolve_bearer(db, secret, scope=TokenScope.mcp) is not None
    assert await resolve_bearer(db, secret) is not None


async def test_last_used_touched_at_most_once_a_minute(client, db):
    u = await make_user(db)
    await login(client, u)
    secret = (await _mint(client))["secret"]
    await resolve_bearer(db, secret)
    row = (await db.execute(select(PersonalAccessToken))).scalar_one()
    first = row.last_used_at
    assert first is not None
    await resolve_bearer(db, secret)
    assert row.last_used_at == first
    row.last_used_at = first - timedelta(minutes=2)
    await resolve_bearer(db, secret)
    assert row.last_used_at > first - timedelta(minutes=1)


async def test_deactivation_revokes_tokens(client, client_factory, db, outbox):
    admin = await make_user(db, role=Role.admin)
    u = await make_user(db)
    cu = client_factory()
    await login(cu, u)
    secret = (await _mint(cu))["secret"]
    await login(client, admin)
    r = await client.post(f"/api/admin/users/{u.id}/deactivate")
    assert r.status_code == 204
    row = (await db.execute(select(PersonalAccessToken))).scalar_one()
    await db.refresh(row)
    assert row.revoked_at is not None
    assert (await client_factory().get("/api/auth/me", headers=_bearer(secret))).status_code == 401


async def test_bearer_post_needs_no_csrf_header(client_factory, db):
    u = await make_user(db)
    c = client_factory()
    await login(c, u)
    secret = (await _mint(c))["secret"]
    bare = client_factory()
    del bare.headers["X-Megoo-Client"]
    r = await bare.post("/api/tokens", json={"name": "x", "scopes": ["mcp"]}, headers=_bearer(secret))
    assert r.status_code == 201
    r = await bare.post("/api/tokens", json={"name": "x", "scopes": ["mcp"]})
    assert r.status_code == 403


async def test_cannot_revoke_someone_elses_token(client_factory, db):
    a = await make_user(db)
    b = await make_user(db)
    ca, cb = client_factory(), client_factory()
    await login(ca, a)
    await login(cb, b)
    made = await _mint(ca)
    assert (await cb.delete(f"/api/tokens/{made['token']['id']}")).status_code == 404
    assert (await cb.get("/api/tokens")).json() == []
    assert (await ca.get("/api/tokens")).json()[0]["revoked_at"] is None


async def test_scopes_required(client, db):
    await login(client, await make_user(db))
    r = await client.post("/api/tokens", json={"name": "t", "scopes": []})
    assert r.status_code == 422


async def test_cookie_only_endpoints_reject_bearer(client, client_factory, db):
    u = await make_user(db)
    await login(client, u)
    secret = (await _mint(client))["secret"]
    r = await client.post("/api/auth/logout", headers=_bearer(secret))
    assert r.status_code == 401
