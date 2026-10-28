"""Plan 10 final review fixes: each test reproduces one finding."""

import pytest

from app.core.config import get_settings
from app.ratelimit import store
from app.ratelimit.limits import Limit
from tests.factories import DEFAULT_PASSWORD, login, make_project, make_user
from tests.mcp.test_workflow_tools import _personal, _tool


@pytest.fixture
def limits(monkeypatch):
    def _set(**values: int) -> None:
        for name, value in values.items():
            monkeypatch.setattr(get_settings(), f"rate_limit_{name}", value)

    return _set


# Important 1: a password with URL characters must neither break the API nor turn the limits off


async def test_password_is_passed_apart_from_the_url(monkeypatch):
    monkeypatch.setattr(get_settings(), "valkey_url", "valkey://localhost:6379/0")
    monkeypatch.setattr(get_settings(), "valkey_password", "megoo-dev-valkey")
    store.reset_client()
    limit = Limit("t", max=1, window=60)
    assert (await store.hit(limit, "s")).allowed
    assert not (await store.hit(limit, "s")).allowed  # really counted, not failing open
    assert await store.healthy()


async def test_a_bad_url_fails_open_instead_of_500(client, db, monkeypatch):
    await login(client, await make_user(db))
    monkeypatch.setattr(get_settings(), "valkey_url", "valkey://:ab/c?d#e@localhost:6379/0")
    store.reset_client()
    assert (await client.get("/api/auth/me")).status_code == 200


# Important 2: anonymous traffic at a shared address must not lock out the people signed in there


async def test_signed_in_people_are_not_blocked_by_anonymous_traffic(client, client_factory, db, limits):
    await login(client, await make_user(db))
    limits(api_per_ip=3)
    stranger = client_factory()
    for _ in range(5):  # someone at the same address, not signed in
        await stranger.get("/api/projects")
    assert (await stranger.get("/api/projects")).status_code == 429
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_an_office_signing_in_together_is_never_limited(client_factory, db, limits):
    limits(api_per_ip=3)
    for _ in range(10):  # the sign-in page asks whether setup is needed, then signs in
        browser = client_factory()
        assert (await browser.get("/api/setup/status")).status_code == 200
        r = await browser.post("/api/auth/login", json={"email": (await make_user(db)).email, "password": DEFAULT_PASSWORD})
        assert r.status_code == 200
        assert (await browser.get("/api/auth/me")).status_code == 200


# Important 3: the question routes and tools that embed the query count as AI calls


@pytest.mark.parametrize("path", ["/api/questions/suggest", "/api/questions"])
async def test_question_routes_count_as_ai(client, db, limits, path):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    await login(client, member)
    limits(ai_per_user=1)
    body = {"project_key": "PAY", "body": "How are webhooks signed?", "title": "Webhooks"}
    assert (await client.post(path, json=body)).status_code != 429
    r = await client.post(path, json=body)
    assert r.status_code == 429 and r.json()["detail"] == "rate_limited"


@pytest.mark.parametrize("tool", ["find_answer", "ask_project"])
async def test_question_tools_count_as_ai(db, tc_factory, limits, tool):
    tc = tc_factory(lifespan=True)
    user = await make_user(db)
    assert tc.post("/api/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}).status_code == 200
    token = _personal(tc)
    limits(ai_per_user=1)
    _tool(tc, token, tool, project_key="NOPE", question="How are webhooks signed?")
    err, out = _tool(tc, token, tool, project_key="NOPE", question="How are webhooks signed?")
    assert err and "rate_limited" in str(out)
