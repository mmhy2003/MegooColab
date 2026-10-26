import uuid

from sqlalchemy import select, update

from app.agents.models import Agent, AgentProgram
from app.jobs.models import Job, JobStatus
from app.kb import access as kb_access
from app.memory import entities, sources
from app.memory.models import EntityKind, ScopeKind
from app.tasks.models import Comment, Task, TaskEvent
from tests.factories import make_project, make_user


async def _queued(db, prefix="mem.extract"):
    rows = (await db.execute(select(Job).where(Job.status == JobStatus.queued, Job.kind == prefix))).scalars()
    return sorted(j.dedupe_key for j in rows)


async def _clear(db):
    await db.execute(update(Job).values(status=JobStatus.done))
    await db.commit()


async def _setup(client, db):
    project, manager, team = await make_project(client, db, "PAY")
    r = await client.post("/api/projects/PAY/tasks", json={"title": "Pay invoices", "type": "task",
                                                          "description_md": "Use Atlas for billing."})
    task = await db.get(Task, uuid.UUID(r.json()["id"]))
    return project, manager, team, task


async def test_each_hook_queues_one_deduped_extract(client, db):
    _project, _manager, team, task = await _setup(client, db)
    assert await _queued(db) == [f"mem.extract:task:{task.id}"]
    await _clear(db)

    c = (await client.post("/api/tasks/PAY-1/comments", json={"body_md": "We retry webhooks."})).json()
    await client.patch(f"/api/comments/{c['id']}", json={"body_md": "We retry webhooks 3 times."})
    await client.patch(f"/api/comments/{c['id']}", json={"body_md": "We retry webhooks 3 times!"})
    assert await _queued(db) == [f"mem.extract:comment:{c['id']}"]
    job = (await db.execute(select(Job).where(Job.kind == "mem.extract"))).scalars().first()
    delay = (await db.execute(select(Job.run_after - Job.created_at).where(Job.id == job.id))).scalar_one()
    assert 55 <= delay.total_seconds() <= 65
    await _clear(db)

    await client.patch("/api/tasks/PAY-1", json={"title": "Pay all invoices"})
    assert await _queued(db) == [f"mem.extract:task:{task.id}"]
    await _clear(db)
    await client.patch("/api/tasks/PAY-1", json={"description_md": "New description"})
    assert await _queued(db) == [f"mem.extract:task:{task.id}"]
    await _clear(db)
    await client.patch("/api/tasks/PAY-1", json={"priority": "high"})
    assert await _queued(db) == []

    await kb_access.ensure_spaces(db)
    space = await kb_access.org_space(db)
    team_space = await kb_access.space_for_team(db, team.id)
    await db.commit()
    doc = (await client.post(f"/api/kb/spaces/{space.id}/documents", json={"title": "Guide", "body_md": "x"})).json()
    await client.put(f"/api/kb/documents/{doc['id']}", json={"base_revision": 1, "body_md": "y"})
    assert await _queued(db) == [f"mem.extract:kb_document:{doc['id']}"]
    await _clear(db)
    await client.post(f"/api/kb/documents/{doc['id']}/move", json={"space_id": str(team_space.id)})
    assert await _queued(db) == [f"mem.extract:kb_document:{doc['id']}"]


async def test_run_finish_and_review_queue_extract(db, tc_factory):
    from tests.workflow.test_engine import _finish, _started

    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _clear(db)
    await _finish(b.manager.id, run, "completed")
    assert f"mem.extract:run:{run.id}" in await _queued(db)


async def test_review_submit_queues_extract(db, tc_factory):
    from app.workflow.models import StepReview
    from tests.workflow.test_build import _building, _complete, _last, _review
    from tests.workflow.test_engine import _finish

    tc = tc_factory(lifespan=True)
    b, run = await _building(db, tc)
    await _complete(run)
    await _finish(b.manager.id, run, "completed")
    review_run = await _last(b.task_id)
    await _clear(db)
    review_id = await _review(review_run, "approved")
    assert f"mem.extract:review:{review_id}" in await _queued(db)
    review = await db.get(StepReview, review_id)
    assert review is not None


async def test_load_source_text_and_scope_per_kind(client, db):
    project, manager, team, task = await _setup(client, db)
    src = await sources.load_source(db, "task", task.id)
    assert src.scope == (ScopeKind.project, uuid.UUID(project["id"]))
    assert src.text == "Pay invoices\n\nUse Atlas for billing." and src.link == "/projects/PAY/tasks/1"
    assert src.label == "PAY-1: Pay invoices"
    c = Comment(task_id=task.id, author_user_id=manager.id, body_md="Comment body")
    db.add(c)
    await db.commit()
    src = await sources.load_source(db, "comment", c.id)
    assert (src.text, src.label, src.scope[0]) == ("Comment body", "Comment on PAY-1", ScopeKind.project)

    from app.agent_runs.models import AgentRun

    agent = Agent(owner_id=manager.id, name="Bot", program=AgentProgram.claude_code)
    db.add(agent)
    await db.flush()
    run = AgentRun(task_id=task.id, agent_id=agent.id, requested_by=manager.id, policy="workspace", prompt="p",
                   status="completed", summary="Added retries.")
    db.add(run)
    await db.flush()
    db.add_all([
        TaskEvent(task_id=task.id, kind="agent_message", data={"text": "Using exponential backoff", "run_id": str(run.id)}),
        TaskEvent(task_id=task.id, kind="agent_file_change", data={"path": "secret/path.py", "run_id": str(run.id)}),
        TaskEvent(task_id=task.id, kind="agent_message", data={"text": "other run", "run_id": str(uuid.uuid4())}),
    ])
    await db.commit()
    src = await sources.load_source(db, "run", run.id)
    assert "Added retries." in src.text and "exponential backoff" in src.text
    assert "secret/path.py" not in src.text and "other run" not in src.text
    names = [e.name for e in src.candidates]
    assert "Bot" in names and manager.name in names

    await kb_access.ensure_spaces(db)
    team_space = await kb_access.space_for_team(db, team.id)
    from app.kb.models import KbDocument

    doc = KbDocument(space_id=team_space.id, title="Team doc", body_md="body", latest_revision=1)
    db.add(doc)
    await db.commit()
    src = await sources.load_source(db, "kb_document", doc.id)
    assert src.scope == (ScopeKind.team, team.id) and src.link == f"/kb/doc/{doc.id}"
    assert src.candidates[0].kind == EntityKind.team


async def test_source_text_capped_12000(client, db):
    _, manager, _, task = await _setup(client, db)
    c = Comment(task_id=task.id, author_user_id=manager.id, body_md="w " * 20_000)
    db.add(c)
    await db.commit()
    assert len((await sources.load_source(db, "comment", c.id)).text) <= 12_000


async def test_candidates_include_people_agents_products(client, db):
    project, manager, _team, task = await _setup(client, db)
    member = await make_user(db)
    task.assignee_user_id = member.id
    linked = await entities.create_product(db, manager, "Hermes", "", [project["id"]])
    mentioned = await entities.create_product(db, manager, "Atlas", "", [])
    unrelated = await entities.create_product(db, manager, "Zeus", "", [])
    await db.commit()
    src = await sources.load_source(db, "task", task.id)
    kinds = [e.kind for e in src.candidates]
    assert kinds[0] == EntityKind.project and kinds[1] == EntityKind.org and EntityKind.team in kinds
    ids = {e.id for e in src.candidates}
    assert {linked.id, mentioned.id} <= ids and unrelated.id not in ids
    assert any(e.kind == EntityKind.user and e.user_id == member.id for e in src.candidates)


async def test_missing_source_returns_none(db):
    assert await sources.load_source(db, "comment", uuid.uuid4()) is None
    assert await sources.load_source(db, "nonsense", uuid.uuid4()) is None



async def test_extract_delay_is_configurable(client, db, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "memory_extract_delay_seconds", 5)
    await _setup(client, db)
    job = (await db.execute(select(Job).where(Job.kind == "mem.extract"))).scalars().first()
    delay = (await db.execute(select(Job.run_after - Job.created_at).where(Job.id == job.id))).scalar_one()
    assert 3 <= delay.total_seconds() <= 8
