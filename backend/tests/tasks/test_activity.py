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


async def test_activity_count_after_a_cursor(client, db):
    """↓ shows how many entries arrived after the newest one the person saw, up to "99+": the server counts what
    the Activity would show after that (at, id) cursor, and stops at `limit`."""
    from sqlalchemy import select

    from app.tasks.models import Task, TaskEvent

    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    await client.post("/api/tasks/PAY-1/comments", json={"body_md": "seen"})
    seen = (await client.get("/api/tasks/PAY-1/activity")).json()[-1]
    for i in range(4):
        await client.post("/api/tasks/PAY-1/comments", json={"body_md": f"new {i}"})
    task = (await db.execute(select(Task).where(Task.number == 1))).scalar_one()
    db.add(TaskEvent(task_id=task.id, kind="pr.status", data={}))  # never shown, so never counted
    await db.commit()

    after = {"after": seen["at"], "after_id": seen["id"]}
    r = await client.get("/api/tasks/PAY-1/activity/count", params=after)
    assert r.status_code == 200 and r.json() == {"count": 4}
    assert (await client.get("/api/tasks/PAY-1/activity/count", params={**after, "limit": 3})).json() == {"count": 3}
    newest = (await client.get("/api/tasks/PAY-1/activity")).json()[-1]
    params = {"after": newest["at"], "after_id": newest["id"]}
    assert (await client.get("/api/tasks/PAY-1/activity/count", params=params)).json() == {"count": 0}
    assert (await client.get("/api/tasks/PAY-1/activity/count", params={**after, "limit": 101})).status_code == 422


async def test_activity_count_needs_access(client, client_factory, db):
    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    seen = (await client.get("/api/tasks/PAY-1/activity")).json()[-1]
    outsider = await make_user(db)
    other = client_factory()
    await login(other, outsider)
    r = await other.get("/api/tasks/PAY-1/activity/count", params={"after": seen["at"], "after_id": seen["id"]})
    assert r.status_code == 404


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


# ---- cards (MC-173) -----------------------------------------------------------

SURFACE = {"version": "1.0", "createSurface": {"surfaceId": "card-1", "catalogId": "urn:megoocolab:a2ui:catalog:v1",
                                               "components": [{"id": "root", "component": "Text", "text": "hi"}]}}


async def _task_id(db):
    from sqlalchemy import select

    from app.tasks.models import Task

    return (await db.execute(select(Task).where(Task.number == 1))).scalar_one().id


async def _card(db, title="Test results", **kw):
    from app.tasks.models import TaskCard

    card = TaskCard(task_id=await _task_id(db), title=title, text="412 passed", surface=SURFACE, **kw)
    db.add(card)
    await db.commit()
    return card


async def test_activity_merges_cards_in_order(client, db):
    from app.agents.models import Agent, AgentProgram

    _, manager, _ = await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    agent = Agent(owner_id=manager.id, name="Builder", program=AgentProgram.codex)
    db.add(agent)
    await db.commit()
    await client.post("/api/tasks/PAY-1/comments", json={"body_md": "before"})
    card = await _card(db, agent_id=agent.id)
    await client.post("/api/tasks/PAY-1/comments", json={"body_md": "after"})
    items = (await client.get("/api/tasks/PAY-1/activity")).json()
    assert [i["type"] for i in items] == ["event", "comment", "card", "comment"]
    shown = items[2]
    assert shown["id"] == str(card.id) and shown["actor"] is None
    assert shown["card"] == {"id": str(card.id), "title": "Test results", "text": "412 passed", "surface": SURFACE,
                             "agent": {"id": str(agent.id), "name": "Builder"}}


async def test_a_personal_card_has_its_person_as_actor(client, db):
    _, manager, _ = await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    await _card(db, user_id=manager.id)
    shown = (await client.get("/api/tasks/PAY-1/activity")).json()[-1]
    assert shown["type"] == "card" and shown["actor"]["name"] == manager.name and shown["card"]["agent"] is None


async def test_a_card_of_a_deleted_agent(client, db):
    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    await _card(db)
    shown = (await client.get("/api/tasks/PAY-1/activity")).json()[-1]
    assert shown["type"] == "card" and shown["actor"] is None and shown["card"]["agent"] is None


async def test_cards_page_with_the_cursor(client, db):
    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    for i in range(5):
        await _card(db, title=f"k{i}")
    page = (await client.get("/api/tasks/PAY-1/activity", params={"limit": 3})).json()
    assert [i["card"]["title"] for i in page] == ["k2", "k3", "k4"]
    cursor = {"limit": 3, "before": page[0]["at"], "before_id": page[0]["id"]}
    earlier = (await client.get("/api/tasks/PAY-1/activity", params=cursor)).json()
    assert [i["card"]["title"] if i["type"] == "card" else i["kind"] for i in earlier] == ["created", "k0", "k1"]


async def test_count_after_counts_cards(client, db):
    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    seen = (await client.get("/api/tasks/PAY-1/activity")).json()[-1]
    await _card(db)
    await _card(db)
    params = {"after": seen["at"], "after_id": seen["id"]}
    assert (await client.get("/api/tasks/PAY-1/activity/count", params=params)).json() == {"count": 2}


async def test_a_card_has_no_images(client, db):
    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    await _card(db)
    shown = (await client.get("/api/tasks/PAY-1/activity")).json()[-1]
    assert shown["type"] == "card" and shown["images"] == []
