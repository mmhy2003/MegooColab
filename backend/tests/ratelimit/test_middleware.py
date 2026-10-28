"""Plan 10 Task 2: the general limits — per signed-in browser or token, and per address for anonymous calls."""

import hashlib
import hmac

import pytest

from app.core.config import get_settings
from app.core.crypto import encrypt
from app.git.models import GitConnection
from app.ratelimit import store
from tests.factories import login, make_user

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


@pytest.fixture
def limits(monkeypatch):
    def _set(**values: int) -> None:
        for name, value in values.items():
            monkeypatch.setattr(get_settings(), f"rate_limit_{name}", value)

    return _set


async def _token(client, scopes=("mcp", "runner")) -> str:
    r = await client.post("/api/tokens", json={"name": "t", "scopes": list(scopes)})
    assert r.status_code == 201, r.text
    return r.json()["secret"]


def _429(r) -> None:
    assert r.status_code == 429, r.text
    assert r.json()["detail"] == "rate_limited"
    assert int(r.headers["retry-after"]) == r.json()["retry_after"] >= 1


async def test_signed_in_user_is_limited_per_session(client, db, limits):
    await login(client, await make_user(db))
    limits(api_per_user=5)
    for _ in range(5):
        assert (await client.get("/api/auth/me")).status_code == 200
    _429(await client.get("/api/auth/me"))


async def test_each_token_has_its_own_budget(client, client_factory, db, limits):
    await login(client, await make_user(db))
    first, second = await _token(client), await _token(client)
    limits(api_per_user=3)
    bare = client_factory()
    for secret in (first, second):
        for _ in range(3):
            assert (await bare.get("/api/tokens/self", headers={"Authorization": f"Bearer {secret}"})).status_code == 200
    _429(await bare.get("/api/tokens/self", headers={"Authorization": f"Bearer {first}"}))


async def test_anonymous_calls_are_limited_per_ip(client, limits):
    limits(api_per_ip=5)
    for _ in range(5):  # not the sign-in pages: they have their own limits (see test_review_fixes)
        assert (await client.get("/api/questions/targets")).status_code == 401
    _429(await client.get("/api/questions/targets"))


async def test_fake_credentials_get_the_ip_blocked(client, limits):
    limits(api_per_ip=5)
    for i in range(5):
        r = await client.get("/api/projects", headers={"Authorization": f"Bearer mgc_fake{i}"})
        assert r.status_code == 401
    _429(await client.get("/api/projects", headers={"Authorization": "Bearer mgc_fake99"}))
    # a forged session cookie is no way round it either
    _429(await client.get("/api/projects", headers={"Cookie": "megoo_session=forged"}))


async def test_health_and_webhooks_are_exempt(client, db, limits):
    conn = GitConnection(name="GHE", kind="github", base_url="https://git.acme.io", token_enc=encrypt("tok"),
                         webhook_secret_enc=encrypt("hook-secret"))
    db.add(conn)
    await db.commit()
    limits(api_per_ip=1)
    for _ in range(3):
        assert (await client.get("/api/health")).status_code == 200
    signature = "sha256=" + hmac.new(b"hook-secret", b"{}", hashlib.sha256).hexdigest()
    for _ in range(3):  # genuine deliveries are anonymous, yet never limited per address
        r = await client.post(f"/api/git/webhooks/{conn.id}", content=b"{}", headers={"X-Hub-Signature-256": signature})
        assert r.status_code == 204


async def test_middleware_fails_open(client, db, limits, monkeypatch):
    await login(client, await make_user(db))
    limits(api_per_user=2, api_per_ip=2)
    monkeypatch.setattr(get_settings(), "valkey_url", "valkey://:x@127.0.0.1:1/0")
    store.reset_client()
    for _ in range(10):
        assert (await client.get("/api/auth/me")).status_code == 200


async def test_mcp_calls_count_per_token(client, client_factory, db, limits, mcp_running):
    await login(client, await make_user(db))
    secret = await _token(client, ("mcp",))
    limits(api_per_user=3)
    bare = client_factory()
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {secret}"}
    for _ in range(3):
        assert (await bare.post("/api/mcp", json=LIST_TOOLS, headers=headers)).status_code != 429
    _429(await bare.post("/api/mcp", json=LIST_TOOLS, headers=headers))


async def test_pages_outside_the_api_are_untouched(client, limits):
    limits(api_per_ip=1)
    for _ in range(3):
        assert (await client.get("/not-an-api-path")).status_code == 404
