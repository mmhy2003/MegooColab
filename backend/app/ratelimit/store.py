"""Fixed-window counters in Valkey. Every Valkey failure allows the request (fail open) and logs a warning at most
once a minute: an outage must not lock everyone out. Admins see it in Admin → Settings."""

import logging
import time
import uuid
from dataclasses import dataclass

import valkey.asyncio as valkey
from fastapi.responses import JSONResponse
from valkey.exceptions import ValkeyError

from app.audit import service as audit
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.ratelimit.limits import Limit

log = logging.getLogger(__name__)

_FAILURES = (ValkeyError, OSError, TimeoutError)
_WARN_EVERY = 60.0
_last_warning = 0.0
_client: valkey.Valkey | None = None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int  # seconds until the window ends; 0 when allowed through a failure


class RateLimited(Exception):
    def __init__(self, limit: str, retry_after: int) -> None:
        super().__init__(f"rate limited: {limit}")
        self.limit = limit
        self.retry_after = retry_after


def _valkey() -> valkey.Valkey:
    global _client
    if _client is None:
        _client = valkey.from_url(get_settings().valkey_url, socket_timeout=1, socket_connect_timeout=1)
    return _client


def reset_client() -> None:
    """Forget the client (tests switch URL or event loop); its pool is dropped with it."""
    global _client
    _client = None


def _warn(e: BaseException) -> None:
    global _last_warning
    now = time.monotonic()
    if now - _last_warning >= _WARN_EVERY:
        _last_warning = now
        log.warning("Valkey unreachable, rate limits are off: %s", e)


def _window(limit: Limit) -> tuple[int, int]:
    """(window index, seconds until it ends)."""
    now = int(time.time())
    index = now // limit.window
    return index, max(1, (index + 1) * limit.window - now)


def _key(kind: str, limit: Limit, subject: str, index: int) -> str:
    return f"{get_settings().valkey_prefix}{kind}:{limit.name}:{subject}:{index}"


async def hit(limit: Limit, subject: str) -> Decision:
    """Counts one and decides: allowed while the count stays within the limit."""
    index, retry_after = _window(limit)
    key = _key("rl", limit, subject, index)
    try:
        async with _valkey().pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, limit.window, nx=True)
            count, _ = await pipe.execute()
    except _FAILURES as e:
        _warn(e)
        return Decision(True, 0)
    return Decision(int(count) <= limit.max, retry_after)


async def peek(limit: Limit, subject: str) -> Decision:
    """Decides without counting: blocked once the count has reached the limit."""
    index, retry_after = _window(limit)
    try:
        count = await _valkey().get(_key("rl", limit, subject, index))
    except _FAILURES as e:
        _warn(e)
        return Decision(True, 0)
    return Decision(int(count or 0) < limit.max, retry_after)


async def healthy() -> bool:
    try:
        return bool(await _valkey().ping())
    except _FAILURES:
        return False


async def raise_if_blocked(
    decision: Decision, limit: Limit, *, ip: str, subject: str, actor_id: uuid.UUID | None = None
) -> None:
    """Returns when allowed. Otherwise audits the block once per counter and window, and raises RateLimited."""
    if decision.allowed:
        return
    index, _ = _window(limit)
    try:
        first = await _valkey().set(_key("rla", limit, subject, index), 1, nx=True, ex=limit.window)
    except _FAILURES as e:
        _warn(e)
        first = False
    if first:
        async with SessionLocal() as db:
            await audit.record(db, "rate_limit.blocked", actor_id=actor_id, data={"limit": limit.name, "ip": ip})
            await db.commit()
    raise RateLimited(limit.name, decision.retry_after)


def rate_limited_response(retry_after: int) -> JSONResponse:
    return JSONResponse(
        {"detail": "rate_limited", "retry_after": retry_after},
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )
