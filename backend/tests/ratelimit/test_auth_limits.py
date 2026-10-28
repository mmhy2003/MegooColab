"""Plan 10 Task 3: sign-in, two-factor, forgot, reset, invite, setup and change-password limits."""

import pyotp
import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import Role
from app.core.config import get_settings
from tests.factories import DEFAULT_PASSWORD, login, make_user


@pytest.fixture
def limits(monkeypatch):
    def _set(**values: int) -> None:
        for name, value in values.items():
            monkeypatch.setattr(get_settings(), f"rate_limit_{name}", value)

    return _set


def _429(r) -> None:
    assert r.status_code == 429, r.text
    assert r.json()["detail"] == "rate_limited" and r.json()["retry_after"] >= 1


async def _sign_in(client, email: str, password: str, code: str | None = None):
    body = {"email": email, "password": password}
    if code is not None:
        body["totp_code"] = code
    return await client.post("/api/auth/login", json=body)


async def _totp_user(client, client_factory, db):
    """A member with two-factor on; returns (user, secret, a fresh signed-out client)."""
    user = await make_user(db)
    await login(client, user)
    secret = (await client.post("/api/auth/totp/setup")).json()["secret"]
    assert (await client.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()})).status_code == 204
    return user, secret, client_factory()


def _wrong(secret: str) -> str:
    right = pyotp.TOTP(secret).now()
    return "000000" if right != "000000" else "111111"


async def test_failed_sign_ins_block_the_ip(client, db, limits):
    user = await make_user(db)
    limits(login_per_ip=3)
    for _ in range(3):
        assert (await _sign_in(client, user.email, "wrong-password")).status_code == 401
    _429(await _sign_in(client, user.email, DEFAULT_PASSWORD))  # even the right password, from this address


async def test_unknown_emails_count_too(client, limits):
    limits(login_per_ip=2)
    for i in range(2):
        assert (await _sign_in(client, f"nobody{i}@x.io", "x")).status_code == 401
    _429(await _sign_in(client, "nobody9@x.io", "x"))


async def test_successful_sign_ins_never_count(client_factory, db, limits):
    limits(login_per_ip=3)
    for _ in range(10):  # one office address, many people signing in
        r = await _sign_in(client_factory(), (await make_user(db)).email, DEFAULT_PASSWORD)
        assert r.status_code == 200


async def test_lockout_still_wins(client, db, limits):
    user = await make_user(db)
    limits(login_per_ip=100)
    for _ in range(10):
        await _sign_in(client, user.email, "wrong-password")
    assert (await _sign_in(client, user.email, DEFAULT_PASSWORD)).status_code == 423


async def test_wrong_codes_after_right_password_limit_the_account(client, client_factory, db, limits):
    user, secret, fresh = await _totp_user(client, client_factory, db)
    limits(totp_per_account=2)
    for _ in range(2):
        assert (await _sign_in(fresh, user.email, DEFAULT_PASSWORD, _wrong(secret))).status_code == 401
    _429(await _sign_in(fresh, user.email, DEFAULT_PASSWORD, pyotp.TOTP(secret).now()))
    # the account, not the address: another address is refused too
    _429(await _sign_in(client_factory(), user.email, DEFAULT_PASSWORD, pyotp.TOTP(secret).now()))


async def test_wrong_password_codes_do_not_count(client, client_factory, db, limits):
    user, secret, fresh = await _totp_user(client, client_factory, db)
    limits(totp_per_account=2)
    for _ in range(5):
        assert (await _sign_in(fresh, user.email, "wrong-password", _wrong(secret))).status_code == 401
    assert (await _sign_in(fresh, user.email, DEFAULT_PASSWORD, pyotp.TOTP(secret).now())).status_code == 200


async def test_code_required_is_not_a_failure(client, client_factory, db, limits):
    user, secret, fresh = await _totp_user(client, client_factory, db)
    limits(login_per_ip=2, totp_per_account=2)
    for _ in range(4):
        r = await _sign_in(fresh, user.email, DEFAULT_PASSWORD)
        assert r.status_code == 401 and r.json()["detail"] == "totp_required"
    assert (await _sign_in(fresh, user.email, DEFAULT_PASSWORD, pyotp.TOTP(secret).now())).status_code == 200


async def test_enable_and_disable_count_wrong_codes(client, db, limits):
    await login(client, await make_user(db))
    secret = (await client.post("/api/auth/totp/setup")).json()["secret"]
    limits(totp_per_account=2)
    for _ in range(2):
        assert (await client.post("/api/auth/totp/enable", json={"code": _wrong(secret)})).status_code == 400
    _429(await client.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()}))


async def test_disable_counts_only_with_the_right_password(client, client_factory, db, limits):
    _user, secret, _ = await _totp_user(client, client_factory, db)
    limits(totp_per_account=2)
    for _ in range(4):
        r = await client.post("/api/auth/totp/disable", json={"password": "wrong-password", "code": _wrong(secret)})
        assert r.status_code == 400
    r = await client.post("/api/auth/totp/disable", json={"password": DEFAULT_PASSWORD, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 204


async def test_forgot_limits_per_email_and_ip(client, db, limits):
    user = await make_user(db)
    limits(forgot_per_email=2, forgot_per_ip=3)
    for _ in range(2):
        assert (await client.post("/api/auth/forgot", json={"email": user.email})).status_code == 204
    _429(await client.post("/api/auth/forgot", json={"email": user.email.upper()}))  # same address, any case
    _429(await client.post("/api/auth/forgot", json={"email": "someone-else@x.io"}))  # the address's 3 are used up


async def test_forgot_answers_the_same_for_unknown_emails(client, limits):
    limits(forgot_per_email=1)
    assert (await client.post("/api/auth/forgot", json={"email": "ghost@x.io"})).status_code == 204
    _429(await client.post("/api/auth/forgot", json={"email": "ghost@x.io"}))


@pytest.mark.parametrize("path", ["/api/auth/reset", "/api/auth/accept-invite"])
async def test_token_pages_count_failures(client, limits, path):
    limits(token_pages_per_ip=2)
    for _ in range(2):
        r = await client.post(path, json={"token": "bogus", "password": "brand-new-pass"})
        assert r.status_code == 400
    _429(await client.post(path, json={"token": "bogus", "password": "brand-new-pass"}))


async def test_token_pages_have_separate_counters(client, limits):
    limits(token_pages_per_ip=1)
    assert (await client.post("/api/auth/reset", json={"token": "bogus", "password": "brand-new-pass"})).status_code == 400
    r = await client.post("/api/auth/accept-invite", json={"token": "bogus", "password": "brand-new-pass"})
    assert r.status_code == 400


async def test_refused_setup_counts(client, db, limits):
    await make_user(db, role=Role.admin)
    limits(token_pages_per_ip=1)
    body = {"org_name": "Acme", "name": "Eve", "email": "eve@x.io", "password": "brand-new-pass"}
    assert (await client.post("/api/setup", json=body)).status_code == 409
    _429(await client.post("/api/setup", json=body))


async def test_change_password_counts_wrong_current_password(client, db, limits):
    await login(client, await make_user(db))
    limits(change_password_per_user=2)
    for _ in range(2):
        r = await client.post("/api/auth/change-password", json={"current_password": "nope", "new_password": "brand-new-pass"})
        assert r.status_code == 400
    _429(await client.post("/api/auth/change-password", json={"current_password": DEFAULT_PASSWORD, "new_password": "brand-new-pass"}))


async def test_blocks_are_audited_once(client, db, limits):
    limits(login_per_ip=1)
    await _sign_in(client, "nobody@x.io", "x")
    for _ in range(3):
        _429(await _sign_in(client, "nobody@x.io", "x"))
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == "rate_limit.blocked"))).scalars().all()
    assert len(rows) == 1 and rows[0].data["limit"] == "login_ip"
