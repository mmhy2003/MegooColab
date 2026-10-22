from app.auth.models import Role
from tests.factories import login, make_project, make_user


async def test_activity_merges_comments_and_events_in_order(client, db):
    await make_project(client, db)
    cols = {c["name"]: c for c in (await client.get("/api/projects/PAY/columns")).json()}
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    r = await client.post("/api/tasks/PAY-1/comments", json={"body_md": "first **comment**"})
    assert r.status_code == 201
    await client.post("/api/tasks/PAY-1/move", json={"column_id": cols["In Progress"]["id"]})
    await client.post("/api/tasks/PAY-1/comments", json={"body_md": "second"})
    items = (await client.get("/api/tasks/PAY-1/activity")).json()
    summary = [(i["type"], i.get("kind") or i.get("body_md")) for i in items]
    assert summary == [
        ("event", "created"),
        ("comment", "first **comment**"),
        ("event", "status_changed"),
        ("comment", "second"),
    ]
    assert items[1]["actor"]["role"] == "manager"


async def test_activity_pagination_before(client, db):
    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    for i in range(5):
        await client.post("/api/tasks/PAY-1/comments", json={"body_md": f"c{i}"})
    page = (await client.get("/api/tasks/PAY-1/activity", params={"limit": 3})).json()
    assert [i.get("body_md") for i in page] == ["c2", "c3", "c4"]
    earlier = (await client.get("/api/tasks/PAY-1/activity", params={"limit": 3, "before": page[0]["at"]})).json()
    assert [i.get("body_md") or i["kind"] for i in earlier] == ["created", "c0", "c1"]


async def test_comment_edit_only_by_author(client, client_factory, db):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    cid = (await client.post("/api/tasks/PAY-1/comments", json={"body_md": "mine"})).json()["id"]
    mc = client_factory()
    await login(mc, member)
    assert (await mc.patch(f"/api/comments/{cid}", json={"body_md": "hijack"})).status_code == 403
    assert (await mc.delete(f"/api/comments/{cid}")).status_code == 403
    r = await client.patch(f"/api/comments/{cid}", json={"body_md": "edited"})
    assert r.status_code == 200 and r.json()["body_md"] == "edited" and r.json()["edited_at"] is not None
    admin = await make_user(db, role=Role.admin)
    ac = client_factory()
    await login(ac, admin)
    assert (await ac.delete(f"/api/comments/{cid}")).status_code == 204
