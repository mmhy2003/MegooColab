import pyotp

from tests.factories import login, make_user


async def _enable_totp(client) -> str:
    r = await client.post("/api/auth/totp/setup")
    assert r.status_code == 200
    secret = r.json()["secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/MegooColab:")
    r = await client.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 204
    return secret


async def test_enable_totp_then_login_requires_code(client, client_factory, db):
    u = await make_user(db, email="t@x.io")
    await login(client, u)
    secret = await _enable_totp(client)
    assert (await client.get("/api/auth/me")).json()["user"]["totp_enabled"] is True

    other = client_factory()
    r = await other.post("/api/auth/login", json={"email": "t@x.io", "password": "correct-horse-1"})
    assert r.status_code == 401 and r.json()["detail"] == "totp_required"
    r = await other.post("/api/auth/login", json={"email": "t@x.io", "password": "correct-horse-1", "totp_code": "000000"})
    assert r.status_code == 401 and r.json()["detail"] == "invalid_credentials"
    r = await other.post("/api/auth/login", json={"email": "t@x.io", "password": "correct-horse-1", "totp_code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200


async def test_enable_rejects_wrong_code(client, db):
    u = await make_user(db)
    await login(client, u)
    await client.post("/api/auth/totp/setup")
    r = await client.post("/api/auth/totp/enable", json={"code": "123456"})
    assert r.status_code == 400 and r.json()["detail"] == "invalid_code"


async def test_disable_requires_password_and_code(client, db):
    u = await make_user(db)
    await login(client, u)
    secret = await _enable_totp(client)
    r = await client.post("/api/auth/totp/disable", json={"password": "wrong-wrong-1", "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 400
    r = await client.post("/api/auth/totp/disable", json={"password": "correct-horse-1", "code": "000000"})
    assert r.status_code == 400
    r = await client.post("/api/auth/totp/disable", json={"password": "correct-horse-1", "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 204
    assert (await client.get("/api/auth/me")).json()["user"]["totp_enabled"] is False
