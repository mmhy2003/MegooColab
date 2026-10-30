"""Worker job: one notification to one device as web push (a send that raises fails the job, which the queue
retries; only this device is sent to again)."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

import requests
from py_vapid import Vapid02
from pywebpush import WebPushException, webpush
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserStatus
from app.jobs import queue
from app.push.keys import VapidKeys, vapid_keys
from app.push.models import PushSubscription

log = logging.getLogger(__name__)

TTL_SECONDS = 86_400  # a device that is off for a day misses the push; the bell still has it
TIMEOUT_SECONDS = 10
GONE = {403, 404, 410}  # uninstalled, data cleared, permission revoked, or subscribed with another key


class _NoRedirects(requests.Session):
    """A push service answers itself; a redirect is never followed (it could point anywhere, inside the network too)."""

    def request(self, method, url, *args, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(method, url, *args, **kwargs)


class PushRetry(Exception):
    """The push service is busy or failing: try this device again later."""


async def deliver(sub: PushSubscription, payload: str, keys: VapidKeys) -> int:
    """POST one encrypted message to the device's push service; its HTTP status. A network error raises."""
    def send() -> int:
        session = _NoRedirects()
        try:
            response = webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=payload,
                vapid_private_key=Vapid02.from_pem(keys.private_key_pem.encode()),
                vapid_claims={"sub": keys.subject},  # webpush adds aud and exp to the dict it is given
                ttl=TTL_SECONDS,
                timeout=TIMEOUT_SECONDS,
                requests_session=session,
            )
        except WebPushException as exc:
            if exc.status_code is None:
                raise
            return exc.status_code
        finally:
            session.close()
        return response.status_code

    return await asyncio.to_thread(send)


@queue.register("notify.push")
async def send_push(db: AsyncSession, payload: dict) -> None:
    sub = await db.get(PushSubscription, uuid.UUID(str(payload["subscription_id"])))
    if sub is None:
        return  # the device was removed meanwhile
    user = await db.get(User, sub.user_id)
    if user is None or user.status != UserStatus.active:
        return
    keys = await vapid_keys(db)
    message = json.dumps({"title": payload["title"], "body": payload["body"], "link": payload["link"]})
    status = await deliver(sub, message, keys)
    if 200 <= status < 300:
        sub.last_used_at = datetime.now(UTC)
    elif status in GONE:
        await db.delete(sub)
    elif status == 429 or status >= 500:
        raise PushRetry(f"push service answered {status}")
    else:  # the message itself was refused (too large, malformed): sending it again would not help
        log.warning("push: dropped a notification the push service refused with %s", status)
