import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.factories import login, make_project, make_user


async def _bound_agent(client, ref="PAY", bind=True):
    r = await client.post("/api/agents", json={"program": "claude_code"})
    assert r.status_code == 201, r.text
    agent = r.json()
    if bind:
        r = await client.put(
            f"/api/agents/{agent['id']}/bindings",
            json={"bindings": [{"project_ref": ref, "local_path": "/repo"}]},
        )
        assert r.status_code == 200, r.text
    return agent


async def _task(client, ref="PAY", **body):
    r = await client.post(f"/api/projects/{ref}/tasks", json={"title": "T", **body})
    assert r.status_code == 201, r.text
    return r.json()


async def test_owner_assigns_own_agent(client, db):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    agent = await _bound_agent(client)
    t = await _task(client)
    r = await client.patch(f"/api/tasks/{t['key']}", json={"assignee_agent_id": agent["id"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["assignee_agent_id"] == agent["id"]
    assert out["assignee_agent"] == {
        "id": agent["id"], "name": agent["name"], "program": "claude_code",
        "owner_id": str(me.id), "status": "offline", "runner": None,
    }
    r = await client.post("/api/projects/PAY/tasks", json={"title": "N", "assignee_agent_id": agent["id"]})
    assert r.status_code == 201 and r.json()["assignee_agent_id"] == agent["id"]


async def test_manager_assigns_anyones_agent(client, client_factory, db):
    me = await make_user(db)
    _, manager, _ = await make_project(client, db, "PAY", me)
    await login(client, me)
    agent = await _bound_agent(client)
    t = await _task(client)
    mc = client_factory()
    await login(mc, manager)
    r = await mc.patch(f"/api/tasks/{t['key']}", json={"assignee_agent_id": agent["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["assignee_agent"]["owner_id"] == str(me.id)


async def test_member_cannot_assign_others_agent_403(client, client_factory, db):
    me = await make_user(db)
    member = await make_user(db)
    await make_project(client, db, "PAY", me, member)
    await login(client, me)
    agent = await _bound_agent(client)
    t = await _task(client)
    mc = client_factory()
    await login(mc, member)
    r = await mc.patch(f"/api/tasks/{t['key']}", json={"assignee_agent_id": agent["id"]})
    assert r.status_code == 403 and r.json()["detail"] == "cannot_use_agent"
    r = await mc.post("/api/projects/PAY/tasks", json={"title": "x", "assignee_agent_id": agent["id"]})
    assert r.status_code == 403 and r.json()["detail"] == "cannot_use_agent"


async def test_unbound_agent_422(client, db):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    agent = await _bound_agent(client, bind=False)
    t = await _task(client)
    r = await client.patch(f"/api/tasks/{t['key']}", json={"assignee_agent_id": agent["id"]})
    assert r.status_code == 422 and r.json()["detail"] == "agent_not_bound"


async def test_unknown_agent_422(client, db):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    t = await _task(client)
    r = await client.patch(
        f"/api/tasks/{t['key']}", json={"assignee_agent_id": "00000000-0000-0000-0000-000000000001"}
    )
    assert r.status_code == 422 and r.json()["detail"] == "unknown_agent"


async def test_assigning_agent_clears_human_and_vice_versa(client, db):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    agent = await _bound_agent(client)
    t = await _task(client, assignee_user_id=str(me.id))
    r = await client.patch(f"/api/tasks/{t['key']}", json={"assignee_agent_id": agent["id"]})
    assert r.json()["assignee_user_id"] is None and r.json()["assignee_agent_id"] == agent["id"]
    r = await client.patch(f"/api/tasks/{t['key']}", json={"assignee_user_id": str(me.id)})
    assert r.json()["assignee_agent_id"] is None and r.json()["assignee_agent"] is None
    assert r.json()["assignee_user_id"] == str(me.id)
    r = await client.patch(f"/api/tasks/{t['key']}", json={"assignee_agent_id": agent["id"]})
    r = await client.patch(f"/api/tasks/{t['key']}", json={"assignee_agent_id": None})
    assert r.json()["assignee_agent_id"] is None
    r = await client.post(
        "/api/projects/PAY/tasks",
        json={"title": "both", "assignee_user_id": str(me.id), "assignee_agent_id": agent["id"]},
    )
    assert r.status_code == 422 and r.json()["detail"] == "single_assignee"


async def test_assigned_event_has_to_agent(client, db):
    from sqlalchemy import select

    from app.tasks.models import TaskEvent

    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    agent = await _bound_agent(client)
    t = await _task(client)
    await client.patch(f"/api/tasks/{t['key']}", json={"assignee_agent_id": agent["id"]})
    await client.patch(f"/api/tasks/{t['key']}", json={"assignee_user_id": str(me.id)})
    events = [
        e.data for e in (await db.execute(select(TaskEvent).where(TaskEvent.kind == "assigned"))).scalars()
    ]
    assert {"from": None, "to": None, "to_agent": agent["id"]} in events
    assert {"from": None, "to": str(me.id), "to_agent": None} in events


async def test_db_rejects_two_assignees(client, db):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    agent = await _bound_agent(client)
    t = await _task(client)
    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE tasks SET assignee_user_id = :u, assignee_agent_id = :a WHERE id = :t"),
            {"u": me.id, "a": agent["id"], "t": t["id"]},
        )
    await db.rollback()


async def test_filter_by_agent(client, db):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    agent = await _bound_agent(client)
    t1 = await _task(client, assignee_agent_id=agent["id"])
    await _task(client, assignee_user_id=str(me.id))
    await _task(client)
    r = await client.get(f"/api/projects/PAY/tasks?assignee=agent:{agent['id']}")
    assert [x["key"] for x in r.json()] == [t1["key"]]
    r = await client.get(f"/api/projects/PAY/tasks?assignee={me.id}")
    assert len(r.json()) == 1
    r = await client.get("/api/projects/PAY/tasks?assignee=agent:nope")
    assert r.status_code == 422
