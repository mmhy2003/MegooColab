"""The admin sets the site's one Telegram bot; its token is checked with Telegram and never leaves the server."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import Role
from app.core.crypto import decrypt
from app.core.db import SessionLocal
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.telegram.client import TelegramError
from app.telegram.models import TelegramLink, TelegramLinkCode
from tests.factories import login, make_user

URL = "/api/admin/telegram"
TOKEN = "42:SECRET-TOKEN"


async def _admin(client, db):
    await login(client, await make_user(db, role=Role.admin))


async def _org() -> OrgSettings:
    async with SessionLocal() as s:
        return await s.get(OrgSettings, ORG_SETTINGS_ID)


async def test_admin_sets_a_bot(client_factory, db, org, telegram):
    admin, member = client_factory(), client_factory()
    await _admin(admin, db)
    await login(member, await make_user(db))
    r = await admin.put(URL, json={"token": TOKEN})
    assert r.status_code == 200, r.text
    assert r.json() == {"bot_username": "megoo_bot"}
    stored = await _org()
    assert decrypt(stored.telegram_token_enc) == TOKEN and stored.telegram_bot_id == 42
    assert (await admin.get(URL)).json() == {"bot_username": "megoo_bot"}
    assert telegram.webhooks_deleted == [TOKEN]  # a bot left with a webhook could never be polled
    assert (await member.get(URL)).status_code == 403
    assert (await member.put(URL, json={"token": TOKEN})).status_code == 403


async def test_refused_and_unreachable_tokens_are_not_saved(client, db, org, telegram):
    await _admin(client, db)
    telegram.me = TelegramError(401, "Unauthorized")
    r = await client.put(URL, json={"token": TOKEN})
    assert (r.status_code, r.json()["detail"]) == (422, "telegram_token_refused")
    telegram.me = TelegramError(0, "could not reach Telegram (getMe)")
    r = await client.put(URL, json={"token": TOKEN})
    assert (r.status_code, r.json()["detail"]) == (502, "telegram_unreachable")
    assert (await client.get(URL)).json() == {"bot_username": None}
    assert (await _org()).telegram_token_enc is None


async def test_same_bot_keeps_links_other_bot_clears_them(client, db, org, telegram):
    await _admin(client, db)
    bea = await make_user(db, name="Bea")
    assert (await client.put(URL, json={"token": TOKEN})).status_code == 200
    db.add(TelegramLink(user_id=bea.id, chat_id=5001))
    db.add(TelegramLinkCode(code="c1", user_id=bea.id, expires_at=datetime.now(UTC) + timedelta(minutes=15)))
    o = await db.get(OrgSettings, ORG_SETTINGS_ID)
    o.telegram_offset = 900
    await db.commit()

    assert (await client.delete(URL)).status_code == 204
    assert (await client.get(URL)).json() == {"bot_username": None}
    assert (await db.execute(select(TelegramLink))).scalars().all()

    assert (await client.put(URL, json={"token": TOKEN})).status_code == 200  # the same bot again
    assert len((await db.execute(select(TelegramLink).execution_options(populate_existing=True))).scalars().all()) == 1
    assert (await _org()).telegram_offset == 900

    telegram.me = {"id": 43, "username": "other_bot"}
    assert (await client.put(URL, json={"token": "43:OTHER"})).json() == {"bot_username": "other_bot"}
    async with SessionLocal() as s:
        assert (await s.execute(select(TelegramLink))).scalars().all() == []
        assert (await s.execute(select(TelegramLinkCode))).scalars().all() == []
        unlinked = (await s.execute(select(AuditLog).where(AuditLog.action == "telegram.unlinked"))).scalar_one()
    assert unlinked.data == {"reason": "bot_changed"} and unlinked.actor_user_id is None
    assert unlinked.target_id == bea.id
    assert (await _org()).telegram_offset is None


async def test_the_token_never_leaves_the_server(client, db, org, telegram):
    await _admin(client, db)
    await client.put(URL, json={"token": TOKEN})
    await client.delete(URL)
    assert TOKEN not in (await client.get(URL)).text
    async with SessionLocal() as s:
        rows = (await s.execute(select(AuditLog).where(AuditLog.action.like("telegram.%")))).scalars().all()
    assert {r.action for r in rows} == {"telegram.bot_set", "telegram.bot_removed"}
    assert all("SECRET" not in json.dumps(r.data) for r in rows)
    assert uuid.UUID(str(rows[0].actor_user_id))
