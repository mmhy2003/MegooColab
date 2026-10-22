from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import Session, UserStatus
from app.core.security import hash_token
from tests.factories import make_user


async def test_login_sets_cookie_and_me_returns_user(client, db):
    u = await make_user(db, email="a@x.io")
    r = await client.post("/api/auth/login", json={"email": "A@x.io", "password": "correct-horse-1"})
    assert r.status_code == 200 and "megoo_session" in r.cookies
    me = await client.get("/api/auth/me")
    assert me.json()["user"]["id"] == str(u.id)


async def test_me_without_session_401(client):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_unknown_email_is_invalid_credentials(client):
    r = await client.post("/api/auth/login", json={"email": "nobody@x.io", "password": "whatever-123"})
    assert r.status_code == 401 and r.json()["detail"] == "invalid_credentials"


async def test_wrong_password_401_and_lockout_after_10(client, db):
    await make_user(db, email="a@x.io")
    for _ in range(10):
        r = await client.post("/api/auth/login", json={"email": "a@x.io", "password": "nope-nope-nope"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"email": "a@x.io", "password": "correct-horse-1"})
    assert r.status_code == 423
    actions = (await db.execute(select(AuditLog.action))).scalars().all()
    assert actions.count("auth.login_failed") == 10 and "auth.locked" in actions


async def test_successful_login_resets_failure_counter(client, db):
    u = await make_user(db, email="a@x.io")
    for _ in range(9):
        await client.post("/api/auth/login", json={"email": "a@x.io", "password": "nope-nope-nope"})
    assert (await client.post("/api/auth/login", json={"email": "a@x.io", "password": "correct-horse-1"})).status_code == 200
    await db.refresh(u)
    assert u.failed_logins == 0


async def test_invited_or_deactivated_cannot_login(client, db):
    await make_user(db, email="d@x.io", status=UserStatus.deactivated)
    r = await client.post("/api/auth/login", json={"email": "d@x.io", "password": "correct-horse-1"})
    assert r.status_code == 401


async def test_logout_invalidates_session(client, db):
    await make_user(db, email="a@x.io")
    await client.post("/api/auth/login", json={"email": "a@x.io", "password": "correct-horse-1"})
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_session_token_stored_hashed(client, db):
    await make_user(db, email="a@x.io")
    r = await client.post("/api/auth/login", json={"email": "a@x.io", "password": "correct-horse-1"})
    raw = r.cookies["megoo_session"]
    rows = (await db.execute(select(Session.token_hash))).scalars().all()
    assert raw not in rows and hash_token(raw) in rows


async def test_setup_signs_admin_in(client):
    await client.post("/api/setup", json={"org_name": "Acme", "name": "Root", "email": "root@acme.io", "password": "correct-horse-1"})
    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["role"] == "admin"


async def test_update_own_name(client, db):
    u = await make_user(db, email="a@x.io")
    await client.post("/api/auth/login", json={"email": "a@x.io", "password": "correct-horse-1"})
    r = await client.patch("/api/auth/me", json={"name": "New Name"})
    assert r.status_code == 200 and r.json()["user"]["name"] == "New Name"
    r = await client.patch("/api/auth/me", json={"name": ""})
    assert r.status_code == 422
