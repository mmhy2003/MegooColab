"""Plan 10 Task 1: fixed-window counters in Valkey, the client address, and the audited 429."""

import uuid

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.core.config import get_settings
from app.ratelimit import store
from app.ratelimit.clientip import client_ip
from app.ratelimit.limits import Limit
from app.ratelimit.store import Decision, RateLimited

LIMIT = Limit("t", max=3, window=60)


async def test_hit_allows_up_to_max_then_blocks():
    s = f"s-{uuid.uuid4()}"
    assert [(await store.hit(LIMIT, s)).allowed for _ in range(4)] == [True, True, True, False]
    blocked = await store.hit(LIMIT, s)
    assert 1 <= blocked.retry_after <= 60


async def test_peek_does_not_count():
    s = f"s-{uuid.uuid4()}"
    for _ in range(5):
        assert (await store.peek(LIMIT, s)).allowed
    for _ in range(3):
        await store.hit(LIMIT, s)
    assert not (await store.peek(LIMIT, s)).allowed


async def test_subjects_and_names_are_separate():
    s = f"s-{uuid.uuid4()}"
    for _ in range(3):
        await store.hit(LIMIT, s)
    assert (await store.hit(Limit("other", 3, 60), s)).allowed
    assert (await store.hit(LIMIT, s + "x")).allowed


async def test_valkey_down_allows_and_reports(monkeypatch):
    monkeypatch.setattr(get_settings(), "valkey_url", "valkey://:x@127.0.0.1:1/0")
    store.reset_client()
    assert (await store.hit(LIMIT, "s")) == Decision(True, 0)
    assert (await store.peek(LIMIT, "s")).allowed
    assert await store.healthy() is False


def test_client_ip_rules(monkeypatch):
    scope = {"type": "http", "client": ("10.0.0.5", 1), "headers": [(b"cf-connecting-ip", b"203.0.113.9")]}
    assert client_ip(scope) == "10.0.0.5"  # the header is ignored unless configured
    monkeypatch.setattr(get_settings(), "client_ip_header", "CF-Connecting-IP")
    assert client_ip(scope) == "203.0.113.9"
    scope["headers"] = [(b"cf-connecting-ip", b"not-an-ip")]
    assert client_ip(scope) == "10.0.0.5"  # an invalid header falls back to the resolved address
    scope["headers"] = [(b"cf-connecting-ip", b"2001:db8:1:2:aaaa::1")]
    assert client_ip(scope) == "2001:db8:1:2::/64"


async def test_raise_if_blocked_audits_once_per_window(db):
    s = f"s-{uuid.uuid4()}"
    for _ in range(3):
        await store.hit(LIMIT, s)
    for _ in range(3):
        with pytest.raises(RateLimited) as e:
            await store.raise_if_blocked(await store.hit(LIMIT, s), LIMIT, ip="1.2.3.4", subject=s)
        assert e.value.retry_after >= 1
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == "rate_limit.blocked"))).scalars().all()
    assert len(rows) == 1 and rows[0].data == {"limit": "t", "ip": "1.2.3.4"}


async def test_429_response_shape(client):
    from app.ratelimit.store import rate_limited_response

    r = rate_limited_response(42)
    assert r.status_code == 429
    assert r.headers["retry-after"] == "42"
    assert r.body == b'{"detail":"rate_limited","retry_after":42}'
