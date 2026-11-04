import json
import uuid

from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import Role
from app.core.crypto import decrypt
from app.secrets.models import Secret
from tests.factories import login, make_project, make_user

VALUE = "s3cr3t-value-123"


def _body(name="STAGING_DB_PASSWORD", value=VALUE):
    return {"name": name, "description": "Staging Postgres password", "value": value}


async def test_value_is_never_returned(client, db):
    me = await make_user(db)
    await login(client, me)
    r = await client.post("/api/secrets", json=_body())
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    texts = [r.text]
    texts.append((await client.get("/api/secrets")).text)
    texts.append((await client.patch(f"/api/secrets/{sid}", json={"description": "New text"})).text)
    r = await client.put(f"/api/secrets/{sid}/value", json={"value": "another-value-9"})
    assert r.status_code == 200, r.text
    texts.append(r.text)
    assert all(VALUE not in t and "another-value-9" not in t for t in texts)
    assert "value" not in r.json()
    row = await db.get(Secret, uuid.UUID(sid), populate_existing=True)
    assert decrypt(row.value_enc) == "another-value-9" and row.user_id == me.id and row.project_id is None


async def test_personal_secrets_are_their_owners_only(client, db):
    me, other = await make_user(db), await make_user(db)
    await login(client, me)
    sid = (await client.post("/api/secrets", json=_body())).json()["id"]
    await login(client, other)
    assert (await client.get("/api/secrets")).json() == []
    assert (await client.patch(f"/api/secrets/{sid}", json={"description": "x"})).status_code == 404
    assert (await client.put(f"/api/secrets/{sid}/value", json={"value": "xxxxxx"})).status_code == 404
    assert (await client.delete(f"/api/secrets/{sid}")).status_code == 404


async def test_project_secrets_managers_write_members_read(client, db):
    member = await make_user(db)
    admin = await make_user(db, role=Role.admin)
    _, manager, _ = await make_project(client, db, "PAY", member)  # logged in as the manager
    base = "/api/projects/PAY/secrets"
    r = await client.post(base, json=_body())
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    await login(client, member)
    listed = await client.get(base)
    assert listed.status_code == 200 and [s["name"] for s in listed.json()] == ["STAGING_DB_PASSWORD"]
    assert (await client.post(base, json=_body("OTHER"))).status_code == 403
    assert (await client.patch(f"{base}/{sid}", json={"description": "x"})).status_code == 403
    assert (await client.put(f"{base}/{sid}/value", json={"value": "xxxxxx"})).status_code == 403
    assert (await client.delete(f"{base}/{sid}")).status_code == 403
    await login(client, admin)
    assert (await client.patch(f"{base}/{sid}", json={"name": "STAGING_PW"})).status_code == 200
    assert (await client.put(f"{base}/{sid}/value", json={"value": "xxxxxx"})).status_code == 200
    assert (await client.delete(f"{base}/{sid}")).status_code == 204


async def test_name_unique_per_scope(client, db):
    await make_project(client, db, "PAY")
    assert (await client.post("/api/projects/PAY/secrets", json=_body())).status_code == 201
    r = await client.post("/api/projects/PAY/secrets", json=_body())
    assert r.status_code == 409 and r.json()["detail"] == "secret_name_taken"
    assert (await client.post("/api/secrets", json=_body())).status_code == 201  # personal: another scope


async def test_reserved_and_invalid_names_are_refused(client, db):
    await login(client, await make_user(db))
    assert (await client.post("/api/secrets", json=_body("PATH"))).json()["detail"] == "secret_name_reserved"
    assert (await client.post("/api/secrets", json=_body("lower"))).json()["detail"] == "secret_name_invalid"


async def test_audit_has_names_not_values(client, db):
    await login(client, await make_user(db))
    sid = (await client.post("/api/secrets", json=_body())).json()["id"]
    await client.patch(f"/api/secrets/{sid}", json={"description": "x"})
    await client.put(f"/api/secrets/{sid}/value", json={"value": "another-value-9"})
    await client.delete(f"/api/secrets/{sid}")
    rows = (await db.execute(select(AuditLog).where(AuditLog.action.like("secret.%")))).scalars().all()
    assert sorted(r.action for r in rows) == ["secret.created", "secret.deleted", "secret.updated", "secret.value_replaced"]
    dumped = json.dumps([r.data for r in rows])
    assert VALUE not in dumped and "another-value-9" not in dumped and "STAGING_DB_PASSWORD" in dumped


async def test_value_too_large(client, db):
    await login(client, await make_user(db))
    r = await client.post("/api/secrets", json=_body(value="x" * 32_769))
    assert r.status_code == 422
    assert (await client.post("/api/secrets", json=_body(value="x" * 32_768))).status_code == 201
