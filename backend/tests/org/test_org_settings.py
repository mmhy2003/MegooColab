from app.auth.models import Role
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from tests.factories import login, make_user

SMTP = {"host": "smtp.example.com", "port": 587, "user": "mailer", "from": "noreply@example.com", "tls": True}


async def _setup_org(db, name="Acme"):
    db.add(OrgSettings(id=ORG_SETTINGS_ID, name=name))
    await db.commit()


async def test_org_name_visible_to_members(client, db):
    await _setup_org(db)
    u = await make_user(db)
    await login(client, u)
    assert (await client.get("/api/org")).json() == {"name": "Acme"}


async def test_smtp_password_encrypted_and_never_returned(client, db):
    await _setup_org(db)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    r = await client.put("/api/admin/settings", json={"name": "Acme Inc", "smtp": {**SMTP, "password": "s3cret-pass"}})
    assert r.status_code == 200
    body = (await client.get("/api/admin/settings")).json()
    assert body["name"] == "Acme Inc"
    assert body["smtp"]["password_set"] is True and "password" not in body["smtp"]
    org = await db.get(OrgSettings, ORG_SETTINGS_ID, populate_existing=True)
    assert org.smtp_password_enc and "s3cret-pass" not in org.smtp_password_enc


async def test_put_without_password_keeps_existing(client, db):
    await _setup_org(db)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    await client.put("/api/admin/settings", json={"name": "Acme", "smtp": {**SMTP, "password": "s3cret-pass"}})
    await client.put("/api/admin/settings", json={"name": "Acme", "smtp": {**SMTP, "host": "smtp2.example.com"}})
    body = (await client.get("/api/admin/settings")).json()
    assert body["smtp"]["host"] == "smtp2.example.com" and body["smtp"]["password_set"] is True


async def test_test_email_reports_smtp_error_as_502(client, db):
    await _setup_org(db)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    await client.put("/api/admin/settings", json={"name": "Acme", "smtp": {**SMTP, "host": "127.0.0.1", "port": 1, "tls": False}})
    r = await client.post("/api/admin/settings/test-email", json={"to": "a@x.io"})
    assert r.status_code == 502


async def test_test_email_without_smtp_400(client, db):
    await _setup_org(db)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    r = await client.post("/api/admin/settings/test-email", json={"to": "a@x.io"})
    assert r.status_code == 400 and r.json()["detail"] == "smtp_not_configured"
