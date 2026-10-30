"""The push preference: a third channel per kind, off until the person ticks it (plan 18)."""

from tests.factories import login, make_user

URL = "/api/me/notification-preferences"


async def test_push_defaults_off(client, db):
    await login(client, await make_user(db))
    prefs = (await client.get(URL)).json()
    assert prefs and all(p["push"] is False for p in prefs)


async def test_push_saved_per_kind(client, db):
    await login(client, await make_user(db))
    r = await client.put(URL, json=[{"kind": "mentioned", "in_app": True, "email": False, "push": True}])
    assert r.status_code == 200
    for prefs in (r.json(), (await client.get(URL)).json()):
        push = {p["kind"]: p["push"] for p in prefs}
        assert push.pop("mentioned") is True
        assert not any(push.values())


async def test_put_without_push_keeps_push_off(client, db):
    await login(client, await make_user(db))
    r = await client.put(URL, json=[{"kind": "assigned", "in_app": False, "email": True}])
    assert r.status_code == 200
    assigned = next(p for p in r.json() if p["kind"] == "assigned")
    assert assigned == {"kind": "assigned", "in_app": False, "email": True, "push": False}
