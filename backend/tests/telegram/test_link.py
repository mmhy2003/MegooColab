"""A person links their own Telegram chat with a one-time Start link; the bot answers what it is sent."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.audit.models import AuditLog
from app.auth.models import Role
from app.core.crypto import encrypt
from app.core.db import SessionLocal
from app.notifications.models import Kind, NotificationPref
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.telegram import service
from app.telegram.models import TelegramLink, TelegramLinkCode
from tests.factories import login, make_user

ME = "/api/me/telegram"
TOKEN = "42:SECRET"
EXPIRED = ("This link has expired. Open MegooColab › Settings › Notifications and press Connect Telegram again.")


async def _bot(db) -> None:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    org.telegram_token_enc, org.telegram_bot_id, org.telegram_bot_username = encrypt(TOKEN), 42, "megoo_bot"
    await db.commit()


def _start(text: str, chat_id: int = 5001, kind: str = "private", update_id: int = 1) -> dict:
    return {"update_id": update_id, "message": {"chat": {"id": chat_id, "type": kind}, "text": text}}


async def _handle(update: dict) -> None:
    async with SessionLocal() as s:
        await service.handle_update(s, TOKEN, update)
        await s.commit()


async def _code(client) -> str:
    r = await client.post(f"{ME}/link")
    assert r.status_code == 200, r.text
    return r.json()["url"].split("start=")[1]


async def _links() -> dict:
    async with SessionLocal() as s:
        return {link.chat_id: link.user_id for link in (await s.execute(select(TelegramLink))).scalars()}


async def _telegram_kinds(user_id) -> set[str]:
    async with SessionLocal() as s:
        return {p.kind for p in (await s.execute(select(NotificationPref).where(
            NotificationPref.user_id == user_id, NotificationPref.telegram.is_(True)))).scalars()}


async def test_connect_makes_a_start_link(client, db, org, telegram):
    await _bot(db)
    bea = await make_user(db, name="Bea")
    await login(client, bea)
    r = await client.post(f"{ME}/link")
    url = r.json()["url"]
    assert url.startswith("https://t.me/megoo_bot?start=")
    code = (await db.execute(select(TelegramLinkCode))).scalar_one()
    assert code.user_id == bea.id and url.endswith(code.code) and len(code.code) <= 64
    left = code.expires_at - datetime.now(UTC)
    assert timedelta(minutes=14) < left <= timedelta(minutes=15)


async def test_start_links_the_chat_and_replies(client, db, org, telegram):
    await _bot(db)
    bea = await make_user(db, name="Bea")
    await login(client, bea)
    await _handle(_start(f"/start {await _code(client)}"))
    assert await _links() == {5001: bea.id}
    assert (await db.execute(select(TelegramLinkCode).execution_options(populate_existing=True))).scalars().all() == []
    assert telegram.sent[-1]["chat_id"] == 5001 and telegram.sent[-1]["text"] == "Connected to MegooColab as Bea."
    assert (await client.get(ME)).json() == {"available": True, "bot_username": "megoo_bot", "linked": True}
    async with SessionLocal() as s:
        linked = (await s.execute(select(AuditLog).where(AuditLog.action == "telegram.linked"))).scalar_one()
    assert linked.actor_user_id == bea.id


async def test_a_code_works_once(client, db, org, telegram):
    await _bot(db)
    bea, ann = await make_user(db, name="Bea"), await make_user(db, name="Ann")
    await login(client, bea)
    code = await _code(client)
    await _handle(_start(f"/start {code}"))
    await _handle(_start(f"/start {code}", chat_id=7007, update_id=2))  # a second tap, or a forwarded link
    assert await _links() == {5001: bea.id}
    assert telegram.sent[-1] == {"token": TOKEN, "chat_id": 7007, "text": EXPIRED, "button_url": None}
    assert ann  # nobody else was linked either


async def test_an_expired_code_is_refused(client, db, org, telegram):
    await _bot(db)
    await login(client, await make_user(db, name="Bea"))
    code = await _code(client)
    await db.execute(update(TelegramLinkCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    await db.commit()
    await _handle(_start(f"/start {code}"))
    assert await _links() == {}
    assert telegram.sent[-1]["text"] == EXPIRED


async def test_a_chat_moves_to_the_new_person(client, db, org, telegram):
    await _bot(db)
    ann, bea = await make_user(db, name="Ann"), await make_user(db, name="Bea")
    db.add(TelegramLink(user_id=ann.id, chat_id=5001))
    await db.commit()
    await login(client, bea)
    await _handle(_start(f"/start {await _code(client)}"))
    assert await _links() == {5001: bea.id}
    async with SessionLocal() as s:
        moved = (await s.execute(select(AuditLog).where(AuditLog.action == "telegram.unlinked"))).scalar_one()
    assert (moved.target_id, moved.data, moved.actor_user_id) == (ann.id, {"reason": "moved"}, None)


async def test_relinking_replaces_your_old_chat(client, db, org, telegram):
    await _bot(db)
    bea = await make_user(db, name="Bea")
    await login(client, bea)
    await _handle(_start(f"/start {await _code(client)}"))
    await _handle(_start(f"/start {await _code(client)}", chat_id=6006, update_id=2))
    assert await _links() == {6006: bea.id}


async def test_first_link_switches_telegram_on_like_push(client_factory, db, org, telegram):
    await _bot(db)
    bea, cai = await make_user(db, name="Bea"), await make_user(db, name="Cai")
    b, c = client_factory(), client_factory()
    await login(b, bea)
    await login(c, cai)
    await b.put("/api/me/notification-preferences",
                json=[{"kind": "assigned", "in_app": True, "email": True, "push": True}])
    await _handle(_start(f"/start {await _code(b)}"))
    assert await _telegram_kinds(bea.id) == {Kind.assigned}
    await _handle(_start(f"/start {await _code(c)}", chat_id=6006, update_id=2))
    assert await _telegram_kinds(cai.id) == {Kind.needs_you, Kind.mentioned}

    assert (await b.delete(ME)).status_code == 204
    await b.put("/api/me/notification-preferences", json=[
        {"kind": "assigned", "in_app": True, "email": True, "push": True, "telegram": False},
        {"kind": "mentioned", "in_app": True, "email": True, "push": False, "telegram": True},
    ])
    await _handle(_start(f"/start {await _code(b)}", update_id=3))
    assert await _telegram_kinds(bea.id) == {Kind.mentioned}  # linking again keeps the person's choices


async def test_other_messages_get_one_line(db, org, telegram):
    await _bot(db)
    await _handle(_start("hello"))
    assert telegram.sent[-1]["text"] == "This bot only sends MegooColab notifications."
    await _handle(_start("/start", update_id=2))
    assert telegram.sent[-1]["text"] == EXPIRED
    sent = len(telegram.sent)
    await _handle(_start("/start abc", kind="group", update_id=3))
    await _handle({"update_id": 4, "edited_message": {"chat": {"id": 1, "type": "private"}, "text": "x"}})
    assert len(telegram.sent) == sent and await _links() == {}


async def test_a_failing_reply_is_not_raised(db, org, telegram):
    from app.telegram.client import TelegramError

    await _bot(db)
    telegram.send_errors.append(TelegramError(403, "Forbidden: bot was blocked by the user"))
    await _handle(_start("hello"))  # no exception


async def test_disconnect(client, db, org, telegram):
    await _bot(db)
    bea = await make_user(db, name="Bea")
    await login(client, bea)
    await _handle(_start(f"/start {await _code(client)}"))
    assert (await client.delete(ME)).status_code == 204
    assert await _links() == {}
    assert (await client.get(ME)).json()["linked"] is False
    async with SessionLocal() as s:
        row = (await s.execute(select(AuditLog).where(AuditLog.action == "telegram.unlinked"))).scalar_one()
    assert (row.data, row.actor_user_id) == ({"reason": "disconnected"}, bea.id)


async def test_no_bot_no_link(client, db, org, telegram):
    await login(client, await make_user(db, role=Role.member))
    r = await client.post(f"{ME}/link")
    assert (r.status_code, r.json()["detail"]) == (409, "telegram_not_set")
    assert (await client.get(ME)).json() == {"available": False, "bot_username": None, "linked": False}
