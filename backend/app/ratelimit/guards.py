"""Named limits inside the routes that own them.

`check` refuses a blocked subject before any work; `count` adds a failure afterwards (the failures-only limits);
`hit` counts every request and refuses past the limit.
"""

import uuid

from starlette.requests import HTTPConnection

from app.ratelimit import limits, store
from app.ratelimit.clientip import client_ip


async def check(name: str, subject: str, conn: HTTPConnection, actor_id: uuid.UUID | None = None) -> None:
    limit = limits.get(name)
    await store.raise_if_blocked(await store.peek(limit, subject), limit, ip=client_ip(conn), subject=subject,
                                 actor_id=actor_id)


async def count(name: str, subject: str) -> None:
    await store.hit(limits.get(name), subject)


async def hit(name: str, subject: str, conn: HTTPConnection, actor_id: uuid.UUID | None = None) -> None:
    limit = limits.get(name)
    await store.raise_if_blocked(await store.hit(limit, subject), limit, ip=client_ip(conn), subject=subject,
                                 actor_id=actor_id)
