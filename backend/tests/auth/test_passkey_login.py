"""A passkey as the second sign-in step, after the right password."""

import pyotp
from sqlalchemy import select, update
from webauthn.helpers import bytes_to_base64url

from app.audit.models import AuditLog
from app.auth.models import Passkey, User, UserStatus, WebauthnChallenge
from tests.auth.softkey import SoftKey
from tests.auth.test_passkeys import add_passkey
from tests.factories import DEFAULT_PASSWORD, login, make_user


async def passkey_user(client, client_factory, db, *, totp: bool = False):
    """A member with a passkey (and an authenticator app); returns (user, key, totp secret, a signed-out client)."""
    user = await make_user(db)
    await login(client, user)
    key, r = await add_passkey(client)
    assert r.status_code == 201, r.text
    secret = None
    if totp:
        secret = (await client.post("/api/auth/totp/setup")).json()["secret"]
        assert (await client.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()})).status_code == 204
    return user, key, secret, client_factory()


async def _sign_in(client, email: str, password: str = DEFAULT_PASSWORD, **extra):
    return await client.post("/api/auth/login", json={"email": email, "password": password, **extra})


async def _audit(db, action: str) -> list[AuditLog]:
    rows = await db.execute(select(AuditLog).where(AuditLog.action == action).execution_options(populate_existing=True))
    return list(rows.scalars())


async def test_password_then_passkey_signs_in(client, client_factory, db):
    user, key, _, fresh = await passkey_user(client, client_factory, db)
    r = await _sign_in(fresh, user.email)
    assert r.status_code == 401 and r.json()["detail"] == "second_factor_required"
    assert r.json()["methods"] == ["passkey"]
    options = r.json()["passkey_options"]
    assert [c["id"] for c in options["allowCredentials"]] == [bytes_to_base64url(key.credential_id)]
    assert options["rpId"] == "localhost" and options["userVerification"] == "preferred"
    r = await _sign_in(fresh, user.email, passkey=key.sign(options))
    assert r.status_code == 200, r.text
    assert (await fresh.get("/api/auth/me")).status_code == 200
    passkey = (await db.execute(select(Passkey).execution_options(populate_existing=True))).scalar_one()
    assert passkey.last_used_at is not None and passkey.sign_count == 1
    assert [e.data for e in await _audit(db, "auth.login") if e.actor_user_id == user.id][-1] == {"second_factor": "passkey"}


async def test_with_an_app_too_both_methods_and_the_code_still_works(client, client_factory, db):
    user, _, secret, fresh = await passkey_user(client, client_factory, db, totp=True)
    r = await _sign_in(fresh, user.email)
    assert r.json()["methods"] == ["passkey", "totp"]
    r = await _sign_in(fresh, user.email, totp_code=pyotp.TOTP(secret).now())
    assert r.status_code == 200
    assert [e.data for e in await _audit(db, "auth.login") if e.actor_user_id == user.id][-1] == {"second_factor": "totp"}


async def test_only_an_app_is_unchanged(client, client_factory, db):
    user = await make_user(db)
    await login(client, user)
    secret = (await client.post("/api/auth/totp/setup")).json()["secret"]
    await client.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()})
    r = await _sign_in(client_factory(), user.email)
    assert r.status_code == 401 and r.json() == {"detail": "totp_required"}


async def test_wrong_password_reveals_nothing(client, client_factory, db):
    user, _, _, fresh = await passkey_user(client, client_factory, db)
    r = await _sign_in(fresh, user.email, "wrong-password-1")
    assert r.status_code == 401 and r.json() == {"detail": "invalid_credentials"}


async def test_assertion_cannot_be_used_twice(client, client_factory, db):
    user, key, _, fresh = await passkey_user(client, client_factory, db)
    options = (await _sign_in(fresh, user.email)).json()["passkey_options"]
    assertion = key.sign(options)
    assert (await _sign_in(fresh, user.email, passkey=assertion)).status_code == 200
    replay = await _sign_in(client_factory(), user.email, passkey=assertion)
    assert replay.status_code == 401 and replay.json()["detail"] == "invalid_credentials"


async def test_someone_elses_passkey_is_refused(client, client_factory, db):
    user, _, _, fresh = await passkey_user(client, client_factory, db)
    other_client = client_factory()
    _, other_key, _, _ = await passkey_user(other_client, client_factory, db)
    options = (await _sign_in(fresh, user.email)).json()["passkey_options"]
    r = await _sign_in(fresh, user.email, passkey=other_key.sign(options))
    assert r.status_code == 401 and r.json()["detail"] == "invalid_credentials"


async def test_a_wrong_origin_is_refused(client, client_factory, db):
    user, key, _, fresh = await passkey_user(client, client_factory, db)
    options = (await _sign_in(fresh, user.email)).json()["passkey_options"]
    key.origin = "http://evil.example"
    assert (await _sign_in(fresh, user.email, passkey=key.sign(options))).status_code == 401


async def test_a_counter_going_backwards_is_refused(client, client_factory, db):
    user, key, _, fresh = await passkey_user(client, client_factory, db)
    options = (await _sign_in(fresh, user.email)).json()["passkey_options"]
    assert (await _sign_in(fresh, user.email, passkey=key.sign(options))).status_code == 200
    options = (await _sign_in(client_factory(), user.email)).json()["passkey_options"]
    r = await _sign_in(client_factory(), user.email, passkey=key.sign(options, sign_count=1))
    assert r.status_code == 401
    assert len(await _audit(db, "auth.passkey_counter_rejected")) == 1


async def test_a_failed_passkey_is_a_failed_sign_in(client, client_factory, db):
    user, key, _, fresh = await passkey_user(client, client_factory, db)
    options = (await _sign_in(fresh, user.email)).json()["passkey_options"]
    key.origin = "http://evil.example"
    await _sign_in(fresh, user.email, passkey=key.sign(options))
    row = (await db.execute(select(User).where(User.id == user.id).execution_options(populate_existing=True))).scalar_one()
    assert row.failed_logins == 1
    assert len(await _audit(db, "auth.login_failed")) == 1


async def test_deactivated_account_gets_no_second_step(client, client_factory, db):
    user, _, _, fresh = await passkey_user(client, client_factory, db)
    await db.execute(update(User).where(User.id == user.id).values(status=UserStatus.deactivated))
    await db.execute(WebauthnChallenge.__table__.delete())
    await db.commit()
    r = await _sign_in(fresh, user.email)
    assert r.status_code == 401 and r.json() == {"detail": "invalid_credentials"}
    assert (await db.execute(select(WebauthnChallenge))).scalars().all() == []
