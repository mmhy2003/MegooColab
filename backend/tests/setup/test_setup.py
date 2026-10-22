from app.auth.models import Role
from tests.factories import make_user


async def test_setup_creates_first_admin(client, db):
    assert (await client.get("/api/setup/status")).json() == {"needs_setup": True}
    r = await client.post("/api/setup", json={"org_name": "Acme", "name": "Root", "email": "Root@Acme.io", "password": "correct-horse-1"})
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "root@acme.io" and r.json()["user"]["role"] == "admin"
    assert (await client.get("/api/setup/status")).json() == {"needs_setup": False}


async def test_setup_refused_once_users_exist(client, db):
    await make_user(db, role=Role.admin)
    r = await client.post("/api/setup", json={"org_name": "X", "name": "Y", "email": "y@x.io", "password": "correct-horse-1"})
    assert r.status_code == 409


async def test_setup_rejects_short_password(client):
    r = await client.post("/api/setup", json={"org_name": "A", "name": "B", "email": "b@a.io", "password": "short"})
    assert r.status_code == 422


async def test_setup_records_audit_entry(client, db):
    from sqlalchemy import select

    from app.audit.models import AuditLog

    await client.post("/api/setup", json={"org_name": "Acme", "name": "Root", "email": "root@acme.io", "password": "correct-horse-1"})
    actions = (await db.execute(select(AuditLog.action))).scalars().all()
    assert actions == ["setup.completed"]
