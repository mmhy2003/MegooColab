from tests.factories import make_project


async def _two(client, db):
    await make_project(client, db)
    a = (await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})).json()
    b = (await client.post("/api/projects/PAY/tasks", json={"title": "b", "type": "task"})).json()
    return a, b


async def test_blocks_shows_blocked_by_on_target(client, db):
    a, b = await _two(client, db)
    r = await client.post(f"/api/tasks/{a['key']}/links", json={"target_key": b["key"], "kind": "blocks"})
    assert r.status_code == 201
    a_links = (await client.get(f"/api/tasks/{a['key']}")).json()["links"]
    b_links = (await client.get(f"/api/tasks/{b['key']}")).json()["links"]
    assert [(l["kind"], l["task"]["key"]) for l in a_links] == [("blocks", b["key"])]
    assert [(l["kind"], l["task"]["key"]) for l in b_links] == [("blocked_by", a["key"])]
    assert (await client.delete(f"/api/tasks/{b['key']}/links/{b_links[0]['id']}")).status_code == 204
    assert (await client.get(f"/api/tasks/{a['key']}")).json()["links"] == []


async def test_duplicate_link_409(client, db):
    a, b = await _two(client, db)
    await client.post(f"/api/tasks/{a['key']}/links", json={"target_key": b["key"], "kind": "relates"})
    r = await client.post(f"/api/tasks/{a['key']}/links", json={"target_key": b["key"], "kind": "relates"})
    assert r.status_code == 409


async def test_self_link_422(client, db):
    a, _ = await _two(client, db)
    r = await client.post(f"/api/tasks/{a['key']}/links", json={"target_key": a["key"], "kind": "relates"})
    assert r.status_code == 422


async def test_watch_unwatch(client, db):
    a, _ = await _two(client, db)
    me = (await client.get("/api/auth/me")).json()["user"]["id"]
    assert me in (await client.get(f"/api/tasks/{a['key']}")).json()["watcher_ids"]  # reporter watches
    assert (await client.delete(f"/api/tasks/{a['key']}/watch")).status_code == 204
    assert me not in (await client.get(f"/api/tasks/{a['key']}")).json()["watcher_ids"]
    assert (await client.put(f"/api/tasks/{a['key']}/watch")).status_code == 204
    assert (await client.put(f"/api/tasks/{a['key']}/watch")).status_code == 204
    assert (await client.get(f"/api/tasks/{a['key']}")).json()["watcher_ids"] == [me]
