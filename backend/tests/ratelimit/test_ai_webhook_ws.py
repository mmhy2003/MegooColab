"""Plan 10 Task 4: AI calls, git webhooks after the signature, and WebSocket connects."""

import hashlib
import hmac

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.crypto import encrypt
from app.git.models import GitConnection
from tests.factories import DEFAULT_PASSWORD, login, make_user
from tests.mcp.test_workflow_tools import _personal, _tool

SECRET = "hook-secret"


@pytest.fixture
def limits(monkeypatch):
    def _set(**values: int) -> None:
        for name, value in values.items():
            monkeypatch.setattr(get_settings(), f"rate_limit_{name}", value)

    return _set


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


async def _connection(db) -> GitConnection:
    conn = GitConnection(name="GHE", kind="github", base_url="https://git.acme.io", token_enc=encrypt("tok"),
                         webhook_secret_enc=encrypt(SECRET))
    db.add(conn)
    await db.commit()
    return conn


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/memory/ask", {"question": "How are webhooks signed?"}),
        ("get", "/api/kb/search?q=webhooks", None),
        ("get", "/api/search?q=webhooks&meaning=true", None),
    ],
)
async def test_ai_calls_have_their_own_limit(client, db, limits, method, path, body):
    await login(client, await make_user(db))
    limits(ai_per_user=2)

    async def call():
        return await (client.post(path, json=body) if method == "post" else client.get(path))

    for _ in range(2):
        assert (await call()).status_code != 429
    r = await call()
    assert r.status_code == 429 and r.json()["detail"] == "rate_limited"
    assert (await client.get("/api/projects")).status_code == 200  # the general limit is separate


async def test_meaning_search_counts_only_with_meaning(client, db, limits):
    await login(client, await make_user(db))
    limits(ai_per_user=1)
    for _ in range(3):
        assert (await client.get("/api/search", params={"q": "webhooks"})).status_code != 429


async def test_testing_an_ai_provider_is_limited(client, db, limits):
    from app.auth.models import Role

    await login(client, await make_user(db, role=Role.admin))
    limits(ai_per_user=1)
    assert (await client.post("/api/admin/ai/jobs/answering/test")).status_code != 429
    assert (await client.post("/api/admin/ai/jobs/answering/test")).status_code == 429


async def test_mcp_ask_memory_is_limited(db, tc_factory, limits):
    tc = tc_factory(lifespan=True)
    user = await make_user(db)
    assert tc.post("/api/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}).status_code == 200
    token = _personal(tc)
    limits(ai_per_user=2)
    for _ in range(2):
        err, out = _tool(tc, token, "ask_memory", question="How are webhooks signed?")
        assert not (err and "rate_limited" in str(out))
    err, out = _tool(tc, token, "ask_memory", question="How are webhooks signed?")
    assert err and "rate_limited" in str(out)


async def test_forged_webhooks_do_not_use_the_connection_budget(client, db, limits):
    conn = await _connection(db)
    limits(webhook_per_connection=2, api_per_ip=100)
    url = f"/api/git/webhooks/{conn.id}"
    for _ in range(10):
        r = await client.post(url, content=b"{}", headers={"X-Hub-Signature-256": "sha256=forged"})
        assert r.status_code == 401
    for _ in range(2):
        assert (await client.post(url, content=b"{}", headers={"X-Hub-Signature-256": _sig(b"{}")})).status_code == 204
    r = await client.post(url, content=b"{}", headers={"X-Hub-Signature-256": _sig(b"{}")})
    assert r.status_code == 429


async def test_forged_webhooks_count_per_ip(client, db, limits):
    conn = await _connection(db)
    limits(api_per_ip=3)
    url = f"/api/git/webhooks/{conn.id}"
    for _ in range(3):
        assert (await client.post(url, content=b"{}", headers={"X-Hub-Signature-256": "sha256=forged"})).status_code == 401
    assert (await client.post(url, content=b"{}", headers={"X-Hub-Signature-256": "sha256=forged"})).status_code == 429


async def test_ws_connects_are_limited(db, tc_factory, limits):
    tc = tc_factory(lifespan=True)
    user = await make_user(db)
    assert tc.post("/api/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}).status_code == 200
    limits(ws_connect=2)
    for _ in range(2):
        with tc.websocket_connect("/api/ws"):
            pass
    with pytest.raises(WebSocketDisconnect) as exc, tc.websocket_connect("/api/ws") as ws:
        ws.receive_json()
    assert exc.value.code == 1008
