"""Closed projects leave the dashboard and the question targets; their answers and their pages stay reachable."""

from tests.dashboard.conftest import add_question, add_task, add_workflow, dash, task_key
from tests.factories import login
from tests.projects.test_project_status import close

from app.dashboard.scope import today


async def test_dashboard_counts_active_projects_only(client, db, world):
    t = await add_task(db, world.pay, user=world.viewer, due=today())
    await add_workflow(db, await add_task(db, world.pay, user=world.viewer), stage="design",
                       status="waiting_human", needs="design_approval")
    await login(client, world.viewer)
    assert len((await dash(client, "mine"))["my_tasks"]) == 1
    await close(db, "PAY", "finished")
    body = await dash(client, "mine")
    assert body["my_tasks"] == [] and body["needs"] == [] and body["projects"] == []
    assert body["numbers"]["open_tasks"] == 0
    assert (await client.get(f"/api/tasks/{task_key(t)}")).status_code == 200  # still opens, read-only
    await login(client, world.admin)
    assert [p["key"] for p in (await dash(client, "all"))["projects"]] == ["WEB"]


async def test_archived_project_keeps_answering_but_takes_no_new_questions(client, db, world):
    q = await add_question(db, world.pay, status="needs_human")
    await close(db, "PAY", "archived")
    await login(client, world.viewer)
    r = await client.post(f"/api/questions/{q.id}/answer", json={"answer_md": "Ops owns it."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "answered"
    assert "PAY" not in [t["key"] for t in (await client.get("/api/questions/targets")).json()]
    await login(client, world.other)
    r = await client.post("/api/questions", json={"project_key": "PAY", "body": "Who owns billing?"})
    assert (r.status_code, r.json()["detail"]) == (409, "project_closed")


async def test_finished_project_can_still_be_asked(client, db, world):
    await close(db, "PAY", "finished")
    await login(client, world.other)
    assert "PAY" in [t["key"] for t in (await client.get("/api/questions/targets")).json()]
    r = await client.post("/api/questions", json={"project_key": "PAY", "body": "Who owns billing?"})
    assert r.status_code == 201, r.text
