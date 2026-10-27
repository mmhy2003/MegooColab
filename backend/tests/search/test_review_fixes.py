"""Plan 9 final review fixes: each test reproduces one finding."""

import uuid
from pathlib import Path

import yaml
from sqlalchemy import select

from app.core.db import SessionLocal
from app.jobs import queue
from app.jobs.models import Job, JobStatus
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.projects.models import BoardColumn
from app.search import client as meili
from app.search import jobs as search_jobs
from app.tasks.models import Task
from tests.factories import make_project
from tests.search.conftest import drain
from tests.search.test_sync import _get

ROOT = Path(__file__).resolve().parents[3]


async def _search_jobs() -> list[Job]:
    async with SessionLocal() as s:
        return list((await s.execute(select(Job).where(Job.kind.like("search.%")))).scalars())


# Important 1: a long Meilisearch outage must not drop index updates


async def test_search_jobs_outlast_a_long_outage(client, db, meili_index):
    await make_project(client, db, "PAY")
    await drain()
    await client.post("/api/projects/PAY/tasks", json={"title": "During the outage", "type": "task"})
    [job] = [j for j in await _search_jobs() if j.status == JobStatus.queued and j.payload.get("kind") == "task"]
    assert job.max_attempts >= 1000
    async with SessionLocal() as s:
        row = await s.get(Job, job.id)
        row.attempts = 50  # a long outage, retried with the capped (hourly) backoff
        await queue.fail(s, row, "SearchUnavailable: down")
        await s.commit()
        assert row.status == JobStatus.queued


# Important 2: an upgraded install (or lost Meilisearch data) gets its rebuild


async def test_ensure_rebuilds_an_install_that_never_rebuilt(client, db, meili_index):
    await make_project(client, db, "PAY")
    await drain()  # a few documents are indexed (as a login would), but the existing data never was
    assert await meili.document_count() > 0
    async with SessionLocal() as s:
        org = await s.get(OrgSettings, ORG_SETTINGS_ID)
        if org is None:  # an installed organization (setup done), upgraded to search
            s.add(OrgSettings(name="Acme"))
        else:
            org.search_rebuilt_at = None
        await s.execute(Job.__table__.delete())
        await s.commit()
    async with SessionLocal() as s:
        await search_jobs.ensure(s, {})
        await s.commit()
    assert [j.kind for j in await _search_jobs()] == ["search.rebuild"]


async def test_ensure_rebuilds_an_index_that_lost_its_settings(client, db, meili_index):
    await make_project(client, db, "PAY")
    await drain()
    async with SessionLocal() as s:
        await search_jobs.rebuild(s, {})
        await s.commit()
    # Meilisearch lost its data; a sync job then re-created the index on the fly, without settings
    await meili.call(lambda: meili.wait(meili.client().delete_index(meili_index)))
    await meili.call(lambda: meili.wait(meili.client().index(meili_index).add_documents(
        [{"id": f"person-{uuid.uuid4()}", "kind": "person", "title": "x", "readers": ["all"]}], primary_key="id")))
    async with SessionLocal() as s:
        await s.execute(Job.__table__.delete())
        await s.commit()
    async with SessionLocal() as s:
        await search_jobs.ensure(s, {})
        await s.commit()
    assert [j.kind for j in await _search_jobs()] == ["search.rebuild"]
    settings = await meili.call(lambda: meili.client().index(meili_index).get_settings())
    assert "readers" in settings["filterableAttributes"]


# Important 3: a rolled-back savepoint keeps the outer transaction's index updates


async def test_savepoint_rollback_keeps_the_outer_transactions_updates(client, db, meili_index):
    project, _, _ = await make_project(client, db, "PAY")
    await drain()
    async with SessionLocal() as s:
        col = (await s.execute(select(BoardColumn).where(BoardColumn.project_id == uuid.UUID(project["id"])).limit(1))).scalar_one()
        task = Task(project_id=col.project_id, number=1, type="task", title="Kept", column_id=col.id, position=1.0)
        s.add(task)
        await s.flush()
        try:
            async with s.begin_nested():
                s.add(Task(project_id=col.project_id, number=2, type="task", title="Rolled back", column_id=col.id,
                           position=2.0))
                await s.flush()
                raise RuntimeError("filing failed")
        except RuntimeError:
            pass
        await s.commit()
        task_id = task.id
    queued = [j.payload for j in await _search_jobs() if j.status == JobStatus.queued]
    assert {"kind": "task", "id": str(task_id)} in queued


# Important 4: snippets show highlighted words, from the comment when only a comment matches


async def test_comment_only_match_shows_the_comment_highlighted(client, db, meili_index):
    await make_project(client, db, "PAY")
    await client.post("/api/projects/PAY/tasks", json={"title": "Card flow", "type": "task",
                                                       "description_md": "Nothing relevant here."})
    await client.post("/api/tasks/PAY-1/comments", json={"body_md": "We should add exponential backoff to it."})
    await drain()
    r = await client.get("/api/search", params={"q": "backoff"})
    [hit] = r.json()["hits"]
    assert "backoff" in hit["snippet"] and "exponential" in hit["snippet"]


# Important 5: facets of a chosen group still list its other values


async def test_facets_of_a_chosen_group_keep_their_other_values(client, db, meili_index):
    project, _, team = await make_project(client, db, "PAY")
    await client.post("/api/projects", json={"key": "WEB", "name": "Rollout website", "description": "",
                                               "team_ids": [str(team.id)]})
    await client.post("/api/projects/PAY/tasks", json={"title": "Rollout pay", "type": "task"})
    await client.post("/api/projects/WEB/tasks", json={"title": "Rollout web", "type": "task"})
    await drain()
    out = (await client.get("/api/search", params={"q": "rollout", "kind": "task"})).json()
    assert out["facets"]["kind"].get("task") == 2
    assert out["facets"]["kind"].get("project") == 1  # still offered, though not chosen
    out = (await client.get("/api/search", params={"q": "rollout", "project": project["id"]})).json()
    assert sorted(p["key"] for p in out["facets"]["project"]) == ["PAY", "WEB"]
    assert out["total"] == 1  # PAY's task


# Important 6: a Meilisearch that won't start does not keep MegooColab down


def test_compose_does_not_wait_for_a_healthy_meilisearch():
    compose = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    dep = compose["services"]["backend"]["depends_on"]["meilisearch"]
    assert dep["condition"] == "service_started"
    assert "worker" in compose["services"] and "meilisearch" not in compose["services"]["worker"].get("depends_on", {})


# Important 7: a renamed label or a column's new category reach the tasks' documents


async def test_label_and_column_changes_reach_their_tasks(client, db, meili_index):
    await make_project(client, db, "PAY")
    label = (await client.post("/api/projects/PAY/labels", json={"name": "bug", "color": "#ff0000"})).json()
    t = (await client.post("/api/projects/PAY/tasks", json={"title": "One", "type": "task",
                                                            "label_ids": [label["id"]]})).json()
    await drain()
    assert (await _get("task", t["id"]))["labels"] == ["bug"]
    assert (await client.patch(f"/api/projects/PAY/labels/{label['id']}", json={"name": "defect"})).status_code == 200
    await drain()
    assert (await _get("task", t["id"]))["labels"] == ["defect"]

    async with SessionLocal() as s:
        task = await s.get(Task, uuid.UUID(t["id"]))
        col = await s.get(BoardColumn, task.column_id)
        other = (await s.execute(select(BoardColumn).where(BoardColumn.project_id == col.project_id,
                                                           BoardColumn.id != col.id,
                                                           BoardColumn.category == "working").limit(1))).scalar_one()
    # make the task's column a second "working" column; another column keeps "before" (one is required)
    r = await client.patch(f"/api/projects/PAY/columns/{col.id}", json={"category": "working"})
    if r.status_code != 200:  # the project needs its only "before" column: move the task, then recategorise
        assert (await client.post("/api/tasks/PAY-1/move", json={"column_id": str(other.id)})).status_code == 200
        await drain()
        r = await client.patch(f"/api/projects/PAY/columns/{other.id}", json={"category": "review"})
        assert r.status_code == 200, r.text
        await drain()
        assert (await _get("task", t["id"]))["status"] == "review"
    else:
        await drain()
        assert (await _get("task", t["id"]))["status"] == "working"

    assert (await client.delete(f"/api/projects/PAY/labels/{label['id']}")).status_code == 204
    await drain()
    assert (await _get("task", t["id"]))["labels"] == []

