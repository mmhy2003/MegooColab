"""Keeping the index current (Plan 9 Task 3): changes made through the API reach Meilisearch through queued jobs."""

import uuid

from sqlalchemy import func, select

from app.auth.models import Role
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.jobs.models import Job, JobStatus
from app.kb import access as kb_access
from app.search import client, documents
from app.search import jobs as search_jobs
from app.tasks.models import Task
from tests.factories import login, make_project, make_user
from tests.search.conftest import drain


async def _get(kind: str, id) -> dict | None:
    """The index document, or None when it is not there."""
    from meilisearch.errors import MeilisearchApiError

    def run():
        try:
            return dict(client.index().get_document(documents.doc_id(kind, id)))
        except MeilisearchApiError:
            return None

    return await client.call(run)


async def _queued(kind_prefix="search.") -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count()).select_from(Job).where(Job.status == JobStatus.queued, Job.kind.like(f"{kind_prefix}%"))
        )


async def _setup(client_, db):
    project, manager, team = await make_project(client_, db, "PAY")
    return project, manager, team


async def test_api_changes_reach_the_index(client, db, meili_index):
    project, manager, team = await _setup(client, db)
    r = await client.post("/api/projects/PAY/tasks", json={"title": "Retry failed card payments", "type": "task"})
    assert r.status_code == 201, r.text
    task = r.json()
    await drain()
    doc = await _get("task", task["id"])
    assert doc and doc["title"] == "Retry failed card payments" and doc["key"] == "PAY-1"

    assert (await client.patch("/api/tasks/PAY-1", json={"description_md": "Backoff 1, 5, 30 minutes"})).status_code == 200
    assert (await client.post("/api/tasks/PAY-1/comments", json={"body_md": "Ahmed: retry three times"})).status_code == 201
    cols = (await client.get("/api/projects/PAY/columns")).json()
    done = next(c for c in cols if c["category"] == "done")
    assert (await client.post("/api/tasks/PAY-1/move", json={"column_id": done["id"]})).status_code == 200
    label = (await client.post("/api/projects/PAY/labels", json={"name": "bug", "color": "#ff0000"})).json()
    assert (await client.patch("/api/tasks/PAY-1", json={"label_ids": [label["id"]],
                                                         "assignee_user_id": str(manager.id)})).status_code == 200
    await drain()
    doc = await _get("task", task["id"])
    assert doc["body"] == "Backoff 1, 5, 30 minutes" and "retry three times" in doc["comments"]
    assert (doc["status"], doc["labels"], doc["assignee"]) == ("done", ["bug"], f"user:{manager.id}")

    space = await kb_access.space_for_project(db, uuid.UUID(project["id"]))
    kd = (await client.post(f"/api/kb/spaces/{space.id}/documents", json={"title": "Retry policy", "body_md": "v1"})).json()
    r = await client.put(f"/api/kb/documents/{kd['id']}", json={"base_revision": 1, "body_md": "every call retried"})
    assert r.status_code == 200, r.text
    assert (await client.post("/api/projects", json={"key": "WEB", "name": "Website", "description": "",
                                                     "team_ids": [str(team.id)]})).status_code == 201
    assert (await client.patch(f"/api/teams/{team.id}", json={"name": "Payments Team"})).status_code == 200
    assert (await client.patch("/api/auth/me", json={"name": "Ann Manager"})).status_code == 200
    agent = (await client.post("/api/agents", json={"program": "codex"})).json()
    q = await client.post("/api/questions", json={"project_key": "WEB", "title": "How do refunds work?",
                                                  "body": "Details please", "task_key": "PAY-1"})
    assert q.status_code == 201, q.text
    await drain()
    assert (await _get("document", kd["id"]))["body"] == "every call retried"
    web = (await client.get("/api/projects/WEB")).json()
    assert (await _get("project", web["id"]))["title"] == "Website"
    assert (await _get("team", team.id))["title"] == "Payments Team"
    assert (await _get("person", manager.id))["title"] == "Ann Manager"
    assert (await _get("agent", agent["id"]))["card"]["owner_name"] == "Ann Manager"
    question = q.json()["question"]
    assert (await _get("question", question["id"]))["title"] == "How do refunds work?"
    r = await client.post(f"/api/questions/{question['id']}/answer", json={"answer_md": "Through the refunds service."})
    assert r.status_code == 200, r.text
    await drain()
    assert "Through the refunds service." in (await _get("question", question["id"]))["body"]


async def test_deletes_leave_the_index(client, db, meili_index):
    project, _, _ = await _setup(client, db)
    t1 = (await client.post("/api/projects/PAY/tasks", json={"title": "One", "type": "task"})).json()
    t2 = (await client.post("/api/projects/PAY/tasks", json={"title": "Two", "type": "task"})).json()
    space = await kb_access.space_for_project(db, uuid.UUID(project["id"]))
    kd = (await client.post(f"/api/kb/spaces/{space.id}/documents", json={"title": "Doc", "body_md": "x"})).json()
    other = await make_user(db)
    await drain()
    assert await _get("task", t1["id"]) and await _get("person", other.id)

    assert (await client.delete("/api/tasks/PAY-1")).status_code == 204
    assert (await client.delete(f"/api/kb/documents/{kd['id']}")).status_code == 204
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    r = await client.post(f"/api/admin/users/{other.id}/deactivate")
    assert r.status_code in (200, 204), r.text
    await drain()
    assert await _get("task", t1["id"]) is None
    assert await _get("document", kd["id"]) is None
    assert await _get("person", other.id) is None
    assert await _get("task", t2["id"]) is not None

    assert (await client.delete("/api/projects/PAY")).status_code == 204
    await drain()
    assert await _get("task", t2["id"]) is None
    assert await _get("project", project["id"]) is None


async def test_jobs_are_deduplicated_per_item(client, db, meili_index):
    await _setup(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "One", "type": "task"})
    await drain()
    async with SessionLocal() as s:
        task = (await s.execute(select(Task))).scalar_one()
        for n in range(10):
            task.title = f"Title {n}"
            await s.flush()
        await s.commit()
    assert await _queued() == 1


async def test_saves_succeed_and_jobs_catch_up_when_meilisearch_is_down(client, db, meili_index):
    await _setup(client, db)
    settings = get_settings()
    good = settings.meili_url
    settings.meili_url = "http://127.0.0.1:9"
    try:
        r = await client.post("/api/projects/PAY/tasks", json={"title": "Saved anyway", "type": "task"})
        assert r.status_code == 201, r.text
        await drain(raise_errors=False)
        async with SessionLocal() as s:
            search = (await s.execute(select(Job).where(Job.kind.like("search.%")))).scalars().all()
        assert search and all(j.status == JobStatus.queued for j in search)  # nothing lost, all retried later
        failed = [j for j in search if j.last_error]
        assert len(failed) == 1 and "SearchUnavailable" in failed[0].last_error
    finally:
        settings.meili_url = good
    await drain()
    assert (await _get("task", r.json()["id"]))["title"] == "Saved anyway"


async def test_ensure_queues_a_rebuild_when_the_index_is_empty(client, db, meili_index):
    await _setup(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "One", "type": "task"})
    async with SessionLocal() as s:
        await s.execute(Job.__table__.delete())
        await s.commit()
    assert await client_count() == 0
    async with SessionLocal() as s:
        await search_jobs.ensure(s, {})
        await s.commit()
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(Job).where(Job.kind == "search.rebuild")) == 1
    await drain()
    assert await client_count() > 0


async def client_count() -> int:
    return await client.document_count()


async def test_rebuild_restores_and_prunes(client, db, meili_index):
    await _setup(client, db)
    t = (await client.post("/api/projects/PAY/tasks", json={"title": "Kept", "type": "task"})).json()
    stray = {"id": f"task-{uuid.uuid4()}", "kind": "task", "title": "Ghost", "readers": ["all"]}
    await client_call_add(stray)
    async with SessionLocal() as s:
        await search_jobs.rebuild(s, {})
        await s.commit()
    assert await _get("task", t["id"]) is not None
    assert await _get("task", stray["id"].removeprefix("task-")) is None


async def client_call_add(doc: dict) -> None:
    await client.call(lambda: client.client().wait_for_task(client.index().add_documents([doc]).task_uid))
