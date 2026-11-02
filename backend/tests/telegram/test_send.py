"""Notifications reach linked people in Telegram: one message per notification, with a button when the site's address
can be opened from Telegram."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.audit.models import AuditLog
from app.auth.models import User, UserStatus
from app.core.config import get_settings
from app.core.crypto import encrypt
from app.core.db import SessionLocal
from app.jobs.models import Job
from app.notifications.models import Kind, NotificationPref
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.telegram.client import TelegramError
from app.telegram.jobs import send_telegram
from app.telegram.messages import button_url, message_text
from app.telegram.models import TelegramLink
from tests.factories import make_user
from tests.notifications.test_core import _notify, _world

SITE = "https://megoo.example.com"


@pytest.fixture
def public_url(monkeypatch):
    def set_to(url: str) -> None:
        monkeypatch.setattr(get_settings(), "public_url", url)

    set_to(SITE)
    return set_to


async def _bot(db) -> None:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    org.telegram_token_enc, org.telegram_bot_id, org.telegram_bot_username = encrypt("42:SECRET"), 42, "megoo_bot"
    await db.commit()


async def _linked(db, user_id, *, kinds=(Kind.mentioned,), chat_id=5001) -> None:
    db.add(TelegramLink(user_id=user_id, chat_id=chat_id))
    await db.commit()
    async with SessionLocal() as s:
        for k in kinds:
            s.add(NotificationPref(user_id=user_id, kind=k, in_app=True, email=False, push=False, telegram=True))
        await s.commit()


async def _jobs() -> list[Job]:
    async with SessionLocal() as s:
        return list((await s.execute(select(Job).where(Job.kind == "notify.telegram").order_by(Job.created_at))).scalars())


async def _run(payload: dict) -> None:
    async with SessionLocal() as s:
        await send_telegram(s, payload)
        await s.commit()


def _payload(user_id, title="PAY-1: a design waits", link="/projects/PAY/board?task=PAY-1") -> dict:
    return {"user_id": str(user_id), "title": title, "body": "Fix login", "link": link}


async def test_mentioned_person_gets_a_telegram_message(client_factory, db, org, telegram, public_url):
    _manager, bea, m, _b, task = await _world(client_factory, db)
    await _bot(db)
    await _linked(db, bea.id)
    r = await m.post(f"/api/tasks/{task['key']}/comments", json={"body_md": f"Look @[Bea](user:{bea.id})"})
    assert r.status_code == 201, r.text
    [job] = await _jobs()
    assert job.payload["user_id"] == str(bea.id) and "token" not in str(job.payload).lower()
    await _run(job.payload)
    [sent] = telegram.sent
    assert sent["chat_id"] == 5001 and sent["text"].startswith("<b>") and "mentioned you on PAY-1" in sent["text"]
    assert sent["button_url"] == f"{SITE}/projects/PAY/board?task=PAY-1"


async def test_not_linked_or_off_means_no_job(client_factory, db, org, telegram):
    _manager, bea, _m, _b, task = await _world(client_factory, db)
    tid = uuid.UUID(task["id"])
    db.add(NotificationPref(user_id=bea.id, kind=Kind.mentioned, in_app=True, email=False, push=False, telegram=True))
    await db.commit()
    await _notify([bea.id], kind=Kind.mentioned, task_id=tid, title="no bot")
    await _bot(db)
    await _notify([bea.id], kind=Kind.mentioned, project_id=None, title="no link")
    db.add(TelegramLink(user_id=bea.id, chat_id=5001))
    await db.commit()
    await _notify([bea.id], kind=Kind.assigned, title="Telegram off for assignments")
    assert await _jobs() == []
    await _notify([bea.id], kind=Kind.mentioned, title="all set")
    assert [j.payload["title"] for j in await _jobs()] == ["all set"]


async def test_message_escapes_html():
    assert message_text("Fix <script> & co", "a < b", None) == "<b>Fix &lt;script&gt; &amp; co</b>\na &lt; b"
    assert message_text("T", "B", f"{SITE}/x") == f"<b>T</b>\nB\n{SITE}/x"


@pytest.mark.parametrize("site", [
    "http://megoo.example.com", "https://localhost:8080", "https://megoo", "https://192.168.1.5", "https://10.0.0.1",
    "https://127.0.0.1", "https://[::1]", "https://169.254.1.1",
])
def test_button_only_for_a_public_https_address(site):
    assert button_url(site, "/x") is None


def test_button_for_a_public_address():
    assert button_url(f"{SITE}/", "/projects/PAY") == f"{SITE}/projects/PAY"
    assert button_url("https://8.8.8.8", "/x") == "https://8.8.8.8/x"


async def test_without_a_button_the_address_is_in_the_text(db, org, telegram, public_url):
    public_url("http://localhost:8080")
    await _bot(db)
    bea = await make_user(db, name="Bea")
    await _linked(db, bea.id)
    await _run(_payload(bea.id))
    [sent] = telegram.sent
    assert sent["button_url"] is None
    assert sent["text"].endswith("\nhttp://localhost:8080/projects/PAY/board?task=PAY-1")


async def test_a_refused_button_is_dropped_and_sent_again(db, org, telegram, public_url):
    bea = await make_user(db, name="Bea")
    await _bot(db)
    await _linked(db, bea.id)
    telegram.send_errors.append(TelegramError(400, "Bad Request: BUTTON_URL_INVALID"))
    await _run(_payload(bea.id))
    [sent] = telegram.sent
    assert sent["button_url"] is None and sent["text"].endswith(f"\n{SITE}/projects/PAY/board?task=PAY-1")


async def test_blocked_or_gone_chat_unlinks(db, org, telegram, public_url):
    bea, cai = await make_user(db, name="Bea"), await make_user(db, name="Cai")
    await _bot(db)
    await _linked(db, bea.id)
    await _linked(db, cai.id, chat_id=6006)
    telegram.send_errors += [TelegramError(403, "Forbidden: bot was blocked by the user"),
                             TelegramError(400, "Bad Request: chat not found")]
    await _run(_payload(bea.id))
    await _run(_payload(cai.id))
    async with SessionLocal() as s:
        assert (await s.execute(select(TelegramLink))).scalars().all() == []
        rows = (await s.execute(select(AuditLog).where(AuditLog.action == "telegram.unlinked"))).scalars().all()
    assert {(r.target_id, r.data["reason"]) for r in rows} == {(bea.id, "blocked"), (cai.id, "chat_gone")}


async def test_rate_limit_waits_and_server_errors_retry(db, org, telegram, public_url):
    bea = await make_user(db, name="Bea")
    await _bot(db)
    await _linked(db, bea.id)
    telegram.send_errors.append(TelegramError(429, "Too Many Requests", retry_after=7))
    await _run(_payload(bea.id))
    [later] = await _jobs()
    assert later.payload == _payload(bea.id)
    assert timedelta(seconds=5) < later.run_after - datetime.now(UTC) <= timedelta(seconds=8)
    telegram.send_errors.append(TelegramError(502, "Bad Gateway"))
    with pytest.raises(TelegramError):
        await _run(_payload(bea.id))
    telegram.send_errors.append(TelegramError(0, "could not reach Telegram (sendMessage)"))
    with pytest.raises(TelegramError):
        await _run(_payload(bea.id))


async def test_no_message_to_a_deactivated_person(db, org, telegram, public_url):
    bea = await make_user(db, name="Bea")
    await _bot(db)
    await _linked(db, bea.id)
    await db.execute(update(User).where(User.id == bea.id).values(status=UserStatus.deactivated))
    await db.commit()
    await _run(_payload(bea.id))
    assert telegram.sent == []


async def test_no_bot_no_message(db, org, telegram, public_url):
    bea = await make_user(db, name="Bea")
    db.add(TelegramLink(user_id=bea.id, chat_id=5001))
    await db.commit()
    await _run(_payload(bea.id))
    assert telegram.sent == []
