"""Adding, listing and removing passkeys (the second sign-in factor)."""

import pyotp
from sqlalchemy import select

from app.audit.models import AuditLog
from tests.auth.softkey import SoftKey
from tests.factories import DEFAULT_PASSWORD, login, make_user


async def add_passkey(client, key: SoftKey | None = None, name: str = "Work laptop"):
    """Adds a passkey to the signed-in person; returns (key, the response)."""
    key = key or SoftKey()
    options = (await client.post("/api/auth/passkeys/options")).json()
    r = await client.post("/api/auth/passkeys", json={"name": name, "credential": key.register(options)})
    return key, r


async def _audit(db, action: str) -> list[AuditLog]:
    rows = await db.execute(select(AuditLog).where(AuditLog.action == action).execution_options(populate_existing=True))
    return list(rows.scalars())


async def test_add_and_list_a_passkey(client, db):
    await login(client, await make_user(db))
    key = SoftKey()
    options = (await client.post("/api/auth/passkeys/options")).json()
    assert options["rp"]["id"] == "localhost" and options["attestation"] == "none"
    assert options["authenticatorSelection"]["residentKey"] == "preferred"
    assert options["authenticatorSelection"]["userVerification"] == "preferred"
    assert [p["alg"] for p in options["pubKeyCredParams"]] == [-7, -257]
    assert options["timeout"] == 120000
    r = await client.post("/api/auth/passkeys", json={"name": " Work laptop ", "credential": key.register(options)})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Work laptop" and r.json()["last_used_at"] is None
    assert set(r.json()) == {"id", "name", "created_at", "last_used_at"}
    assert [p["name"] for p in (await client.get("/api/auth/passkeys")).json()] == ["Work laptop"]
    [entry] = await _audit(db, "auth.passkey_added")
    assert entry.data == {"name": "Work laptop"}


async def test_a_registration_with_a_used_or_wrong_challenge_fails(client, db):
    await login(client, await make_user(db))
    key = SoftKey()
    options = (await client.post("/api/auth/passkeys/options")).json()
    credential = key.register(options)
    assert (await client.post("/api/auth/passkeys", json={"name": "A", "credential": credential})).status_code == 201
    again = await client.post("/api/auth/passkeys", json={"name": "B", "credential": SoftKey().register(options)})
    assert again.status_code == 400 and again.json()["detail"] == "passkey_invalid"
    options = (await client.post("/api/auth/passkeys/options")).json()
    evil = SoftKey(origin="http://evil.example").register(options)
    r = await client.post("/api/auth/passkeys", json={"name": "C", "credential": evil})
    assert r.status_code == 400 and r.json()["detail"] == "passkey_invalid"
    assert len((await client.get("/api/auth/passkeys")).json()) == 1


async def test_the_same_authenticator_is_not_added_twice(client, db):
    await login(client, await make_user(db))
    key, _ = await add_passkey(client)
    options = (await client.post("/api/auth/passkeys/options")).json()
    from webauthn.helpers import bytes_to_base64url

    assert [c["id"] for c in options["excludeCredentials"]] == [bytes_to_base64url(key.credential_id)]
    r = await client.post("/api/auth/passkeys", json={"name": "Again", "credential": key.register(options)})
    assert r.status_code == 409 and r.json()["detail"] == "passkey_exists"


async def test_at_most_ten_passkeys(client, db):
    await login(client, await make_user(db))
    for i in range(10):
        _, r = await add_passkey(client, name=f"Key {i}")
        assert r.status_code == 201
    r = await client.post("/api/auth/passkeys/options")
    assert r.status_code == 409 and r.json()["detail"] == "too_many_passkeys"


async def test_a_name_is_needed(client, db):
    await login(client, await make_user(db))
    _, r = await add_passkey(client, name="   ")
    assert r.status_code == 422
    _, r = await add_passkey(client, name="x" * 101)
    assert r.status_code == 422


async def test_someone_elses_list_is_never_shown(client, client_factory, db):
    await login(client, await make_user(db))
    await add_passkey(client)
    other = client_factory()
    await login(other, await make_user(db))
    assert (await other.get("/api/auth/passkeys")).json() == []


async def _remove_options(client, passkey_id: str) -> dict:
    r = await client.post(f"/api/auth/passkeys/{passkey_id}/remove-options")
    assert r.status_code == 200, r.text
    return r.json()


async def _remove(client, passkey_id: str, **body):
    return await client.request("DELETE", f"/api/auth/passkeys/{passkey_id}", json=body)


async def test_removing_needs_the_password_and_a_second_factor(client, db):
    await login(client, await make_user(db))
    key, r = await add_passkey(client)
    pid = r.json()["id"]
    r = await _remove(client, pid, password=DEFAULT_PASSWORD)
    assert r.status_code == 400 and r.json()["detail"] == "invalid_password_or_code"
    r = await _remove(client, pid, password="wrong-password-1", passkey=key.sign(await _remove_options(client, pid)))
    assert r.status_code == 400
    r = await _remove(client, pid, password=DEFAULT_PASSWORD, passkey=key.sign(await _remove_options(client, pid)))
    assert r.status_code == 204
    assert (await client.get("/api/auth/passkeys")).json() == []
    [entry] = await _audit(db, "auth.passkey_removed")
    assert entry.data == {"name": "Work laptop"}


async def test_removing_with_the_authenticator_code(client, db):
    await login(client, await make_user(db))
    _, r = await add_passkey(client)
    secret = (await client.post("/api/auth/totp/setup")).json()["secret"]
    await client.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()})
    r = await _remove(client, r.json()["id"], password=DEFAULT_PASSWORD, totp_code=pyotp.TOTP(secret).now())
    assert r.status_code == 204


async def test_someone_elses_passkey_cannot_be_removed(client, client_factory, db):
    await login(client, await make_user(db))
    _, r = await add_passkey(client)
    other = client_factory()
    await login(other, await make_user(db))
    assert (await other.post(f"/api/auth/passkeys/{r.json()['id']}/remove-options")).status_code == 404
    r = await _remove(other, r.json()["id"], password=DEFAULT_PASSWORD, totp_code="123456")
    assert r.status_code == 404 and r.json()["detail"] == "not_found"


async def test_removing_the_last_passkey_turns_two_factor_off(client, client_factory, db):
    user = await make_user(db)
    await login(client, user)
    key, r = await add_passkey(client)
    pid = r.json()["id"]
    await _remove(client, pid, password=DEFAULT_PASSWORD, passkey=key.sign(await _remove_options(client, pid)))
    r = await client_factory().post("/api/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD})
    assert r.status_code == 200
