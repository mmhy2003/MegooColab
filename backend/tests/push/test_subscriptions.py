"""This person's devices that get push (plan 18)."""

import uuid

import pytest
from sqlalchemy import func, select

from app.auth.models import Role
from app.push.models import PushSubscription
from app.push.service import device_name
from tests.factories import login, make_user

URL = "/api/push/subscriptions"
CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def _body(endpoint: str | None = None, p256dh: str = "BKey", auth: str = "auth1") -> dict:
    return {"endpoint": endpoint or f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4()}",
            "keys": {"p256dh": p256dh, "auth": auth}}


async def _count(db, user_id) -> int:
    return await db.scalar(select(func.count()).select_from(PushSubscription)
                           .where(PushSubscription.user_id == user_id))


async def test_key_is_served(client, db):
    await login(client, await make_user(db))
    r = await client.get("/api/push/key")
    assert r.status_code == 200 and len(r.json()["public_key"]) == 87


async def test_register_list_delete(client, db):
    await login(client, await make_user(db))
    r = await client.post(URL, json=_body(), headers={"User-Agent": CHROME_WINDOWS})
    assert r.status_code == 201, r.text
    device = r.json()
    assert device["name"] == "Chrome on Windows" and device["endpoint"].startswith("https://")
    assert [d["id"] for d in (await client.get(URL)).json()] == [device["id"]]
    assert (await client.delete(f"{URL}/{device['id']}")).status_code == 204
    assert (await client.get(URL)).json() == []


async def test_register_moves_endpoint_to_new_user(client, client_factory, db):
    a, b = await make_user(db), await make_user(db)
    await login(client, a)
    other = client_factory()
    await login(other, b)
    endpoint = f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4()}"
    assert (await client.post(URL, json=_body(endpoint))).status_code == 201
    r = await other.post(URL, json=_body(endpoint, p256dh="BNew", auth="auth2"))
    assert r.status_code == 201
    assert (await client.get(URL)).json() == []
    assert [d["endpoint"] for d in (await other.get(URL)).json()] == [endpoint]
    row = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint)
                            .execution_options(populate_existing=True))).scalar_one()
    assert (row.user_id, row.p256dh, row.auth) == (b.id, "BNew", "auth2")


async def test_cannot_delete_someone_elses(client, client_factory, db):
    await login(client, await make_user(db))
    device = (await client.post(URL, json=_body())).json()
    other = client_factory()
    await login(other, await make_user(db))
    r = await other.delete(f"{URL}/{device['id']}")
    assert r.status_code == 404 and r.json()["detail"] == "push_subscription_not_found"


async def test_rejects_non_https_endpoint(client, db):
    await login(client, await make_user(db))
    r = await client.post(URL, json=_body("http://push.example.com/x"))
    assert r.status_code == 422 and r.json()["detail"] == "invalid_push_endpoint"


async def test_bearer_token_cannot_register(client, client_factory, db):
    await login(client, await make_user(db))
    secret = (await client.post("/api/tokens", json={"name": "mcp", "scopes": ["mcp"]})).json()["secret"]
    bearer = client_factory()
    r = await bearer.post(URL, json=_body(), headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code in (401, 403)


async def test_password_reset_deletes_subscriptions(client, client_factory, db, outbox):
    me = await make_user(db, email="push@x.io")
    await login(client, me)
    for _ in range(2):
        assert (await client.post(URL, json=_body())).status_code == 201
    other = client_factory()
    assert (await other.post("/api/auth/forgot", json={"email": "push@x.io"})).status_code == 204
    url = next(w for w in outbox.sent[0][2].split() if "/reset/" in w)
    token = url.rstrip("/").rsplit("/", 1)[-1]
    assert (await other.post("/api/auth/reset", json={"token": token, "password": "fresh-pass-12"})).status_code == 204
    assert await _count(db, me.id) == 0


async def test_deactivation_deletes_subscriptions(client, client_factory, db):
    me = await make_user(db)
    await login(client, me)
    assert (await client.post(URL, json=_body())).status_code == 201
    admin = client_factory()
    await login(admin, await make_user(db, role=Role.admin))
    assert (await admin.post(f"/api/admin/users/{me.id}/deactivate")).status_code == 204
    assert await _count(db, me.id) == 0


@pytest.mark.parametrize(("ua", "name"), [
    (CHROME_WINDOWS, "Chrome on Windows"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Version/18.0 Mobile/15E148 Safari/604.1", "Safari on iPhone"),
    ("Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile "
     "Safari/537.36", "Chrome on Android"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14.6; rv:131.0) Gecko/20100101 Firefox/131.0", "Firefox on macOS"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 "
     "Safari/537.36 Edg/130.0.0.0", "Edge on Windows"),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", "Firefox on Linux"),
    ("Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
     "Mobile/15E148 Safari/604.1", "Safari on iPad"),
    (None, "Browser on this device"),
])
def test_device_names(ua, name):
    assert device_name(ua) == name


@pytest.mark.parametrize("endpoint", [
    "https://attacker.example.com/push",
    "https://10.0.0.5/internal",
    "https://fcm.googleapis.com.evil.io/x",
    "https://user@fcm.googleapis.com/x",
])
async def test_rejects_endpoints_outside_the_push_services(client, db, endpoint):
    """Final review C1: the worker POSTs to whatever is registered, so only the browsers' push services are allowed."""
    await login(client, await make_user(db))
    r = await client.post(URL, json=_body(endpoint))
    assert r.status_code == 422 and r.json()["detail"] == "invalid_push_endpoint"


@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/abc",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
    "https://web.push.apple.com/QAbc",
    "https://wns2-par02p.notify.windows.com/w/?token=abc",
])
async def test_accepts_the_browsers_push_services(client, db, endpoint):
    await login(client, await make_user(db))
    assert (await client.post(URL, json=_body(endpoint))).status_code == 201


async def test_a_person_has_at_most_ten_devices(client, db):
    """Final review C1: registering an eleventh device drops the one registered first."""
    me = await make_user(db)
    await login(client, me)
    ids = [(await client.post(URL, json=_body())).json()["id"] for _ in range(11)]
    left = {d["id"] for d in (await client.get(URL)).json()}
    assert len(left) == 10 and ids[0] not in left and ids[-1] in left
