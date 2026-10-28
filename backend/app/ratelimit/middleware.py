"""The general limits on every `/api` HTTP request (Plan 10).

- With a credential (a bearer token, or the session cookie): the address must not be blocked, then the credential
  counts against `api_user`. A 401 answer counts against the address, so rotating made-up tokens or cookies gets
  the address blocked.
- Without one: the address counts against `api_ip`.

The credential is counted by its hash, before any database lookup: one budget per signed-in browser and one per
token (personal or agent run). `/api/health` is exempt, and so are anonymous git webhooks, which their route counts
after checking the signature.
"""

import hashlib
from collections.abc import Mapping
from contextvars import ContextVar

from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.service import SESSION_COOKIE
from app.ratelimit import limits, store
from app.ratelimit.clientip import client_ip

# the current request's subject: its credential (`tok:` / `ses:`), else `ip:<address>`; the AI limit counts it
current_subject: ContextVar[str | None] = ContextVar("current_subject", default=None)

_EXEMPT = frozenset({"/api/health"})
_WEBHOOKS = "/api/git/webhooks/"


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def credential_subject(headers: Headers, cookies: Mapping[str, str]) -> str | None:
    scheme, _, value = headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return f"tok:{_digest(value.strip())}"
    session = cookies.get(SESSION_COOKIE)
    return f"ses:{_digest(session)}" if session else None


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/") or path in _EXEMPT:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        subject = credential_subject(headers, cookie_parser(headers.get("cookie", "")))
        ip = client_ip(scope)
        api_ip = limits.get("api_ip")
        if subject is None:
            if not path.startswith(_WEBHOOKS):
                decision = await store.hit(api_ip, ip)
                if not decision.allowed:
                    await self._refuse(decision, api_ip, ip, ip, scope, receive, send)
                    return
        else:
            decision = await store.peek(api_ip, ip)
            if not decision.allowed:
                await self._refuse(decision, api_ip, ip, ip, scope, receive, send)
                return
            api_user = limits.get("api_user")
            decision = await store.hit(api_user, subject)
            if not decision.allowed:
                await self._refuse(decision, api_user, ip, subject, scope, receive, send)
                return

        status: list[int] = []

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status.append(message["status"])
            await send(message)

        token = current_subject.set(subject or f"ip:{ip}")
        try:
            await self.app(scope, receive, _send)
        finally:
            current_subject.reset(token)
        if subject is not None and status and status[0] == 401:
            await store.hit(api_ip, ip)

    @staticmethod
    async def _refuse(
        decision: store.Decision, limit: limits.Limit, ip: str, subject: str, scope: Scope, receive: Receive, send: Send
    ) -> None:
        try:
            await store.raise_if_blocked(decision, limit, ip=ip, subject=subject)
        except store.RateLimited as e:
            await store.rate_limited_response(e.retry_after)(scope, receive, send)
