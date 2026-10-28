"""Plan 10 Task 5: admins see whether the rate limits are on."""

from app.auth.models import Role
from app.core.config import get_settings
from app.ratelimit import store
from tests.factories import login, make_user


async def test_admin_sees_rate_limit_status(client, db):
    await login(client, await make_user(db, role=Role.admin))
    assert (await client.get("/api/admin/rate-limits")).json() == {"working": True}


async def test_status_says_off_when_valkey_is_down(client, db, monkeypatch):
    await login(client, await make_user(db, role=Role.admin))
    monkeypatch.setattr(get_settings(), "valkey_url", "valkey://:x@127.0.0.1:1/0")
    store.reset_client()
    assert (await client.get("/api/admin/rate-limits")).json() == {"working": False}


async def test_members_cannot_see_it(client, db):
    await login(client, await make_user(db))
    assert (await client.get("/api/admin/rate-limits")).status_code == 403
