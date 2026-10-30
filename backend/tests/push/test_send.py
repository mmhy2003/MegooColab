"""Sending notifications as web push: one job per device, dead devices cleaned up (plan 18)."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.auth.models import UserStatus
from app.core.db import SessionLocal
from app.jobs.models import Job
from app.notifications import service
from app.notifications.models import Kind, Notification, NotificationPref
from app.push import jobs as push_jobs
from app.push.models import PushSubscription
from tests.factories import make_user


async def _device(db, user, n: int = 0) -> PushSubscription:
    sub = PushSubscription(user_id=user.id, endpoint=f"https://push.example.com/{uuid.uuid4()}", p256dh=f"key{n}",
                           auth=f"auth{n}", name="Chrome on Windows")
    db.add(sub)
    await db.commit()
    return sub


async def _prefs(db, user, kind=Kind.mentioned, *, in_app=True, email=False, push=True) -> None:
    db.add(NotificationPref(user_id=user.id, kind=kind, in_app=in_app, email=email, push=push))
    await db.commit()


async def _notify(user, kind=Kind.mentioned) -> None:
    async with SessionLocal() as s:
        await service.notify(s, [user.id], kind, title="PAY-1: you were mentioned", body="Look at this",
                             link="/projects/PAY/board?task=PAY-1")
        await s.commit()


async def _push_jobs() -> list[Job]:
    async with SessionLocal() as s:
        return list((await s.execute(select(Job).where(Job.kind == "notify.push").order_by(Job.id))).scalars())


@pytest.fixture
def sent(monkeypatch):
    """deliver() recorded instead of called; `status` is what the push service answers."""
    calls: list[dict] = []
    state = {"status": 201}

    async def deliver(sub, payload, keys):
        calls.append({"endpoint": sub.endpoint, "payload": json.loads(payload), "subject": keys.subject})
        return state["status"]

    monkeypatch.setattr(push_jobs, "deliver", deliver)
    return calls, state


async def test_no_push_when_unticked(db):
    me = await make_user(db)
    await _device(db, me)
    await _notify(me)
    assert await _push_jobs() == []


async def test_one_job_per_device(db):
    me = await make_user(db)
    a, b = await _device(db, me, 1), await _device(db, me, 2)
    await _prefs(db, me)
    await _notify(me)
    jobs = await _push_jobs()
    assert sorted(j.payload["subscription_id"] for j in jobs) == sorted([str(a.id), str(b.id)])
    assert all(j.payload["title"] == "PAY-1: you were mentioned" and j.payload["body"] == "Look at this"
               and j.payload["link"] == "/projects/PAY/board?task=PAY-1" for j in jobs)


async def test_push_independent_of_in_app(db):
    me = await make_user(db)
    await _device(db, me)
    await _prefs(db, me, in_app=False, email=False, push=True)
    await _notify(me)
    async with SessionLocal() as s:
        rows = (await s.execute(select(Notification).where(Notification.user_id == me.id))).scalars().all()
    assert rows == [] and len(await _push_jobs()) == 1


async def test_job_sends_payload(db, sent):
    calls, _ = sent
    me = await make_user(db)
    sub = await _device(db, me)
    await _prefs(db, me)
    await _notify(me)
    [job] = await _push_jobs()
    async with SessionLocal() as s:
        await push_jobs.send_push(s, job.payload)
        await s.commit()
    assert calls == [{"endpoint": sub.endpoint, "subject": calls[0]["subject"], "payload": {
        "title": "PAY-1: you were mentioned", "body": "Look at this", "link": "/projects/PAY/board?task=PAY-1"}}]
    await db.refresh(sub)
    assert sub.last_used_at is not None


def _payload(sub) -> dict:
    return {"subscription_id": str(sub.id), "title": "t", "body": "b", "link": "/"}


async def _exists(sub) -> bool:
    async with SessionLocal() as s:
        return await s.get(PushSubscription, sub.id) is not None


@pytest.mark.parametrize("status", [404, 410, 403])
async def test_gone_device_is_deleted(db, sent, status):
    sent[1]["status"] = status
    sub = await _device(db, await make_user(db))
    async with SessionLocal() as s:
        await push_jobs.send_push(s, _payload(sub))
        await s.commit()
    assert not await _exists(sub)


async def test_other_client_error_is_dropped(db, sent):
    sent[1]["status"] = 400
    sub = await _device(db, await make_user(db))
    async with SessionLocal() as s:
        await push_jobs.send_push(s, _payload(sub))
        await s.commit()
    assert await _exists(sub)


@pytest.mark.parametrize("status", [500, 429])
async def test_server_error_retries(db, sent, status):
    sent[1]["status"] = status
    sub = await _device(db, await make_user(db))
    async with SessionLocal() as s:
        with pytest.raises(Exception):
            await push_jobs.send_push(s, _payload(sub))
    assert await _exists(sub)


async def test_inactive_user_gets_nothing(db, sent):
    calls, _ = sent
    me = await make_user(db, status=UserStatus.deactivated)
    sub = await _device(db, me)
    async with SessionLocal() as s:
        await push_jobs.send_push(s, _payload(sub))
    assert calls == []


async def test_removed_device_is_skipped(db, sent):
    calls, _ = sent
    me = await make_user(db)
    sub = await _device(db, me)
    payload = _payload(sub)
    await db.delete(sub)
    await db.commit()
    async with SessionLocal() as s:
        await push_jobs.send_push(s, payload)
    assert calls == []


async def test_deliver_encrypts_and_signs_with_the_server_key(db, monkeypatch):
    """The real pywebpush path, up to the HTTP POST: our stored PEM signs a VAPID header, the body is encrypted."""
    import base64

    import pywebpush
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from app.push.keys import vapid_keys

    browser = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    sub = PushSubscription(user_id=(await make_user(db)).id, endpoint="https://push.example.com/abc",
                           p256dh=b64(browser), auth=b64(b"0123456789abcdef"), name="Chrome on Windows")
    keys = await vapid_keys(db)
    await db.commit()
    seen = {}

    class Response:
        status_code = 201
        text = ""
        headers: dict = {}

    def post(url, data=None, headers=None, timeout=None, **kw):
        seen.update(url=url, headers=headers, body=data)
        return Response()

    monkeypatch.setattr(pywebpush.requests, "post", post)
    assert await push_jobs.deliver(sub, json.dumps({"title": "t", "body": "b", "link": "/"}), keys) == 201
    assert seen["url"] == "https://push.example.com/abc"
    assert {k.lower(): v for k, v in seen["headers"].items()}["ttl"] == str(push_jobs.TTL_SECONDS)
    assert seen["headers"]["Authorization"].startswith("vapid t=")  # RFC 8292, signed with our key
    assert seen["headers"]["Authorization"].endswith(f"k={keys.public_key}")
    assert seen["body"] and b"PAY" not in seen["body"] and b'"title"' not in seen["body"]  # encrypted
