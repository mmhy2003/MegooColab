"""An admin (or the server command) turns off someone's two-factor sign-in: their way back in."""

import pyotp
from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import Passkey, Role
from app.core.db import SessionLocal
from tests.auth.test_passkeys import add_passkey
from tests.factories import DEFAULT_PASSWORD, login, make_user


async def _member_with_both(client_factory, db):
    member = await make_user(db, email="locked@x.io", name="Lou Locked")
    c = client_factory()
    await login(c, member)
    await add_passkey(c)
    secret = (await c.post("/api/auth/totp/setup")).json()["secret"]
    await c.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()})
    return member, c


async def _admin(client, db, name="Ada Admin"):
    admin = await make_user(db, role=Role.admin, name=name)
    await login(client, admin)
    return admin


async def test_admin_turns_off_someones_two_factor(client, client_factory, db, outbox):
    member, member_client = await _member_with_both(client_factory, db)
    admin = await _admin(client, db)
    r = await client.post(f"/api/admin/users/{member.id}/reset-two-factor")
    assert r.status_code == 204, r.text
    assert (await member_client.get("/api/auth/me")).json()["user"]["totp_enabled"] is False  # still signed in
    async with SessionLocal() as s:
        assert (await s.execute(select(Passkey).where(Passkey.user_id == member.id))).scalars().all() == []
        [entry] = (await s.execute(select(AuditLog).where(AuditLog.action == "auth.two_factor_reset"))).scalars().all()
    assert (entry.actor_user_id, entry.target_id, entry.data) == (admin.id, member.id, {"via": "admin"})
    r = await client_factory().post("/api/auth/login", json={"email": member.email, "password": DEFAULT_PASSWORD})
    assert r.status_code == 200
    [(to, subject, body)] = outbox.sent
    assert to == "locked@x.io" and subject == "Two-factor sign-in turned off"
    assert body.startswith("Ada Admin turned off two-factor sign-in for your MegooColab account.")


async def test_listed_until_reset(client, client_factory, db):
    member, _ = await _member_with_both(client_factory, db)
    await _admin(client, db)

    async def row():
        return next(r for r in (await client.get("/api/admin/users/details")).json() if r["user_id"] == str(member.id))

    assert (await row())["totp"] is True and (await row())["passkeys"] == 1
    await client.post(f"/api/admin/users/{member.id}/reset-two-factor")
    assert ((await row())["totp"], (await row())["passkeys"]) == (False, 0)


async def test_not_on_oneself(client, db):
    admin = await _admin(client, db)
    r = await client.post(f"/api/admin/users/{admin.id}/reset-two-factor")
    assert r.status_code == 409 and r.json()["detail"] == "cannot_reset_own_two_factor"


async def test_only_admins(client, client_factory, db):
    member, _ = await _member_with_both(client_factory, db)
    await login(client, await make_user(db, role=Role.manager))
    assert (await client.post(f"/api/admin/users/{member.id}/reset-two-factor")).status_code == 403
    assert (await client.get("/api/admin/users/details")).status_code == 403


async def test_unknown_person(client, db):
    await _admin(client, db)
    r = await client.post("/api/admin/users/00000000-0000-0000-0000-000000000000/reset-two-factor")
    assert r.status_code == 404


async def test_no_email_set_up_still_resets(client, client_factory, db):
    member, _ = await _member_with_both(client_factory, db)
    await _admin(client, db)
    assert (await client.post(f"/api/admin/users/{member.id}/reset-two-factor")).status_code == 204


async def test_cli_resets_by_email(client_factory, db, capsys):
    from app.cli import run

    member, _ = await _member_with_both(client_factory, db)
    assert await run(["reset-two-factor", "LOCKED@x.io"]) == 0
    assert "Two-factor sign-in turned off for locked@x.io." in capsys.readouterr().out
    async with SessionLocal() as s:
        [entry] = (await s.execute(select(AuditLog).where(AuditLog.action == "auth.two_factor_reset"))).scalars().all()
    assert (entry.actor_user_id, entry.data) == (None, {"via": "cli"})
    assert await run(["reset-two-factor", "nobody@x.io"]) == 1
    assert "No account with that email." in capsys.readouterr().out
