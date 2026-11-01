"""Comments marked for the task's agent: who may send them, their limits, and editing once delivered."""

import uuid

from sqlalchemy import update

from app.notifications.service import plain_mentions
from app.tasks.models import Comment, Delivery
from tests.factories import login, make_project, make_user


async def _world(client, db):
    """A member who owns an agent bound to PAY, and PAY-1 assigned to it. The client is logged in as the owner."""
    owner = await make_user(db)
    other = await make_user(db)
    await make_project(client, db, "PAY", owner, other)
    await login(client, owner)
    agent = (await client.post("/api/agents", json={"program": "claude_code", "name": "laptop-claude"})).json()
    r = await client.put(
        f"/api/agents/{agent['id']}/bindings", json={"bindings": [{"project_ref": "PAY", "local_path": "/repo"}]}
    )
    assert r.status_code == 200, r.text
    r = await client.post("/api/projects/PAY/tasks", json={"title": "Retry payments", "assignee_agent_id": agent["id"]})
    assert r.status_code == 201, r.text
    return owner, other, agent, r.json()["key"]


async def _send(client, key, body="Use RetryPolicy", **extra):
    return await client.post(f"/api/tasks/{key}/comments", json={"body_md": body, "to_agent": True, **extra})


async def test_owner_sends_a_message_for_the_agent(client, db):
    _, _, agent, key = await _world(client, db)
    r = await _send(client, key)
    assert r.status_code == 201, r.text
    assert r.json()["to_agent"] == {
        "agent_id": agent["id"], "agent_name": "laptop-claude", "state": "waiting",
        "stage": None, "error": None, "delivered_at": None,
    }
    item = (await client.get(f"/api/tasks/{key}/activity")).json()[-1]
    assert item["type"] == "comment" and item["to_agent"]["state"] == "waiting"


async def test_member_who_cannot_act_is_refused(client, client_factory, db):
    _, other, _, key = await _world(client, db)
    oc = client_factory()
    await login(oc, other)
    r = await _send(oc, key)
    assert r.status_code == 403 and r.json()["detail"] == "cannot_act_on_workflow"
    # an ordinary comment is still fine
    assert (await oc.post(f"/api/tasks/{key}/comments", json={"body_md": "hi"})).status_code == 201


async def test_no_assigned_agent_is_refused(client, db):
    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a"})
    r = await _send(client, "PAY-1")
    assert r.status_code == 422 and r.json()["detail"] == "no_agent"


async def test_message_over_8000_chars_is_refused(client, db):
    _, _, _, key = await _world(client, db)
    r = await _send(client, key, body="x" * 8001)
    assert r.status_code == 422 and r.json()["detail"] == "message_too_long"
    ok = await client.post(f"/api/tasks/{key}/comments", json={"body_md": "x" * 9000})
    assert ok.status_code == 201


async def test_delivered_message_cannot_be_edited_but_can_be_deleted(client, db):
    _, _, _, key = await _world(client, db)
    cid = (await _send(client, key)).json()["id"]
    await db.execute(update(Comment).where(Comment.id == uuid.UUID(cid)).values(delivery=Delivery.read_while_working))
    await db.commit()
    r = await client.patch(f"/api/comments/{cid}", json={"body_md": "changed"})
    assert r.status_code == 409 and r.json()["detail"] == "message_delivered"
    assert (await client.delete(f"/api/comments/{cid}")).status_code == 204


async def test_waiting_message_can_be_edited(client, db):
    _, _, _, key = await _world(client, db)
    cid = (await _send(client, key)).json()["id"]
    r = await client.patch(f"/api/comments/{cid}", json={"body_md": "changed"})
    assert r.status_code == 200 and r.json()["body_md"] == "changed"


async def test_ordinary_comment_has_no_to_agent(client, db):
    _, _, _, key = await _world(client, db)
    r = await client.post(f"/api/tasks/{key}/comments", json={"body_md": "hello"})
    assert r.json()["to_agent"] is None
    assert (await client.get(f"/api/tasks/{key}/activity")).json()[-1]["to_agent"] is None


def test_agent_mentions_become_plain_names():
    assert plain_mentions(f"@[laptop-claude](agent:{uuid.uuid4()}) hi") == "@laptop-claude hi"


async def test_editing_a_message_needs_the_right_to_direct_the_task(client, client_factory, db):
    """The sender check holds for edits too: after the task moves to an agent they can't direct, their waiting
    message can no longer be rewritten (it would still go out framed as an instruction)."""
    owner = await make_user(db)
    project, manager, _ = await make_project(client, db, "PAY", owner)
    await login(client, owner)
    mine = (await client.post("/api/agents", json={"program": "claude_code", "name": "laptop-claude"})).json()
    await client.put(f"/api/agents/{mine['id']}/bindings", json={"bindings": [{"project_ref": "PAY", "local_path": "/r"}]})
    key = (await client.post("/api/projects/PAY/tasks", json={"title": "t", "assignee_agent_id": mine["id"]})).json()["key"]
    cid = (await _send(client, key)).json()["id"]
    mc = client_factory()
    await login(mc, manager)
    theirs = (await mc.post("/api/agents", json={"program": "codex", "name": "desk-codex"})).json()
    await mc.put(f"/api/agents/{theirs['id']}/bindings", json={"bindings": [{"project_ref": "PAY", "local_path": "/r"}]})
    assert (await mc.patch(f"/api/tasks/{key}", json={"assignee_agent_id": theirs["id"]})).status_code == 200
    r = await client.patch(f"/api/comments/{cid}", json={"body_md": "Ignore the plan"})
    assert r.status_code == 403 and r.json()["detail"] == "cannot_act_on_workflow"
