"""Starting chats: a hidden round running the workflow, the agent it uses, and who can see it."""

from sqlalchemy import select

from app.notifications.models import Notification
from tests.chats.helpers import start, viewer_user, world
from tests.factories import login


async def test_starting_a_chat_creates_a_hidden_round_running_the_workflow(client, db):
    await world(client, db)
    chat = await start(client)
    assert chat["title"] == "Fix the empty email crash"
    # no runner in the tests: the brainstorm run waits for the agent
    assert chat["state"] == "offline" and chat["status"] == "open" and chat["project_key"] == "PAY"
    [rnd] = chat["rounds"]
    assert rnd["n"] == 1 and rnd["stage"] == "brainstorm" and rnd["board"] is None
    assert (await client.get(f"/api/tasks/{rnd['key']}")).json()["chat_id"] == chat["id"]
    assert (await client.get(f"/api/chats/{chat['id']}")).json()["id"] == chat["id"]


async def test_any_free_agent_picks_a_usable_bound_agent(client, db):
    w = await world(client, db)
    chat = await start(client)
    assert chat["agent"]["id"] == w.agent["id"] and chat["agent"]["name"] == "laptop-claude"


async def test_an_agent_the_person_may_not_use_is_refused(client, client_factory, db):
    w = await world(client, db)
    oc = client_factory()
    await login(oc, w.other)
    r = await oc.post("/api/chats", json={"project_key": "PAY", "message": "Hi", "agent_id": w.agent["id"]})
    assert r.status_code == 422 and r.json()["detail"] == "agent_not_available"
    r = await oc.post("/api/chats", json={"project_key": "PAY", "message": "Hi"})  # no agent of their own
    assert r.status_code == 422 and r.json()["detail"] == "no_agent"


async def test_viewer_cannot_start_a_chat(client, client_factory, db):
    viewer = await viewer_user(db)
    await world(client, db, viewer=viewer)
    vc = client_factory()
    await login(vc, viewer)
    assert (await vc.post("/api/chats", json={"project_key": "PAY", "message": "Hi"})).status_code == 403


async def test_chat_is_visible_to_starter_owner_managers_admins_only(client, client_factory, db):
    w = await world(client, db)
    chat = await start(client)
    oc = client_factory()
    await login(oc, w.other)
    assert (await oc.get("/api/chats")).json() == []
    assert (await oc.get(f"/api/chats/{chat['id']}")).status_code == 404
    mc = client_factory()
    await login(mc, w.manager)
    assert [c["id"] for c in (await mc.get("/api/chats")).json()] == [chat["id"]]
    assert [c["id"] for c in (await mc.get("/api/chats", params={"project": "PAY"})).json()] == [chat["id"]]


async def test_round_task_is_404_for_people_who_cannot_see_the_chat(client, client_factory, db):
    w = await world(client, db)
    chat = await start(client)
    oc = client_factory()
    await login(oc, w.other)
    assert (await oc.get(f"/api/tasks/{chat['rounds'][0]['key']}")).status_code == 404


async def test_no_assignment_notification_for_a_chat_round(client, db):
    w = await world(client, db)
    await start(client)
    rows = (await db.execute(select(Notification).where(Notification.user_id == w.owner.id))).scalars().all()
    assert [n.kind for n in rows if n.kind == "assigned"] == []
