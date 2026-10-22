from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.auth.models import OneTimeToken, Role
from app.core.email import get_mailer
from tests.factories import login, make_user


async def _admin(client, db):
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    return admin


def _token_from(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


async def test_invite_then_accept_activates_and_signs_in(client, client_factory, db, outbox):
    await _admin(client, db)
    r = await client.post("/api/admin/users/invite", json={"email": "New@x.io", "name": "New", "role": "member"})
    assert r.status_code == 201
    url = r.json()["invite_url"]
    assert url.startswith("http://localhost:8080/invite/")
    assert r.json()["user"]["status"] == "invited"
    assert outbox.sent[0][0] == "new@x.io" and url in outbox.sent[0][2]

    invitee = client_factory()
    r = await invitee.post("/api/auth/accept-invite", json={"token": _token_from(url), "password": "brand-new-pass"})
    assert r.status_code == 200
    me = await invitee.get("/api/auth/me")
    assert me.json()["user"]["status"] == "active"


async def test_invite_token_single_use(client, client_factory, db, outbox):
    await _admin(client, db)
    url = (await client.post("/api/admin/users/invite", json={"email": "n@x.io", "name": "N", "role": "member"})).json()["invite_url"]
    other = client_factory()
    assert (await other.post("/api/auth/accept-invite", json={"token": _token_from(url), "password": "brand-new-pass"})).status_code == 200
    r = await other.post("/api/auth/accept-invite", json={"token": _token_from(url), "password": "another-pass-1"})
    assert r.status_code == 400 and r.json()["detail"] == "invalid_or_expired_token"


async def test_invite_token_expired(client, client_factory, db, outbox):
    await _admin(client, db)
    url = (await client.post("/api/admin/users/invite", json={"email": "n@x.io", "name": "N", "role": "member"})).json()["invite_url"]
    await db.execute(update(OneTimeToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    await db.commit()
    r = await client_factory().post("/api/auth/accept-invite", json={"token": _token_from(url), "password": "brand-new-pass"})
    assert r.status_code == 400 and r.json()["detail"] == "invalid_or_expired_token"


async def test_invite_without_smtp_still_returns_url(app, client, db):
    app.dependency_overrides[get_mailer] = lambda: None
    await _admin(client, db)
    r = await client.post("/api/admin/users/invite", json={"email": "n@x.io", "name": "N", "role": "member"})
    assert r.status_code == 201 and "/invite/" in r.json()["invite_url"]
    assert r.json()["email_sent"] is False


async def test_member_cannot_invite(client, db, outbox):
    member = await make_user(db, role=Role.member)
    await login(client, member)
    r = await client.post("/api/admin/users/invite", json={"email": "n@x.io", "name": "N", "role": "member"})
    assert r.status_code == 403


async def test_direct_create_forces_password_change(client, client_factory, db, outbox):
    await _admin(client, db)
    r = await client.post("/api/admin/users", json={"email": "d@x.io", "name": "D", "role": "member", "temporary_password": "temp-pass-123"})
    assert r.status_code == 201 and r.json()["user"]["must_change_password"] is True
    user_client = client_factory()
    assert (await user_client.post("/api/auth/login", json={"email": "d@x.io", "password": "temp-pass-123"})).status_code == 200
    r = await user_client.get("/api/teams")
    assert r.status_code == 403 and r.json()["detail"] == "password_change_required"
    r = await user_client.post("/api/auth/change-password", json={"current_password": "temp-pass-123", "new_password": "my-own-pass-1"})
    assert r.status_code == 204
    assert (await user_client.get("/api/teams")).status_code == 200


async def test_change_password_rejects_wrong_current(client, db):
    u = await make_user(db)
    await login(client, u)
    r = await client.post("/api/auth/change-password", json={"current_password": "wrong-wrong-1", "new_password": "my-own-pass-1"})
    assert r.status_code == 400 and r.json()["detail"] == "invalid_current_password"


async def test_reset_revokes_existing_sessions(client, client_factory, db, outbox):
    u = await make_user(db, email="r@x.io")
    await login(client, u)
    other = client_factory()
    assert (await other.post("/api/auth/forgot", json={"email": "R@x.io"})).status_code == 204
    body = outbox.sent[0][2]
    url = next(w for w in body.split() if "/reset/" in w)
    assert (await other.post("/api/auth/reset", json={"token": _token_from(url), "password": "fresh-pass-12"})).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401
    r = await other.post("/api/auth/login", json={"email": "r@x.io", "password": "fresh-pass-12"})
    assert r.status_code == 200


async def test_admin_reset_link(client, client_factory, db, outbox):
    await _admin(client, db)
    u = await make_user(db, email="r@x.io")
    r = await client.post(f"/api/admin/users/{u.id}/reset-link")
    assert r.status_code == 201 and "/reset/" in r.json()["reset_url"]


async def test_forgot_unknown_email_is_204_and_sends_nothing(client, outbox):
    r = await client.post("/api/auth/forgot", json={"email": "ghost@x.io"})
    assert r.status_code == 204 and outbox.sent == []


async def test_duplicate_email_409(client, db, outbox):
    await _admin(client, db)
    await make_user(db, email="taken@x.io")
    r = await client.post("/api/admin/users/invite", json={"email": "Taken@x.io", "name": "T", "role": "member"})
    assert r.status_code == 409
