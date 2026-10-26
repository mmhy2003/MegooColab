import litellm
import pytest
from sqlalchemy import select, update

from app.auth.models import Role
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.jobs import worker
from app.jobs.models import Job, JobStatus
from app.kb import access, search
from app.kb.models import KbChunk
from tests.factories import login, make_project, make_team, make_user


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_fake", False)


async def _world(client, db):
    member = await make_user(db)
    outsider = await make_user(db)
    _project, manager, team = await make_project(client, db, "PAY", member)
    await make_team(db, outsider)
    await access.ensure_spaces(db)
    org = await access.org_space(db)
    team_space = await access.space_for_team(db, team.id)
    await db.commit()
    await login(client, member)
    return {"member": member, "outsider": outsider, "org": org, "team": team_space, "manager": manager}


async def _doc(client, space_id, title, body=""):
    r = await client.post(f"/api/kb/spaces/{space_id}/documents", json={"title": title, "body_md": body})
    assert r.status_code == 201, r.text
    return r.json()


async def _drain():
    """Runs queued jobs until none is due."""
    for _ in range(200):
        if not await worker.run_once():
            return
    raise AssertionError("queue did not drain")


async def _chunks(doc_id):
    async with SessionLocal() as s:
        return (
            await s.execute(select(KbChunk).where(KbChunk.document_id == doc_id).order_by(KbChunk.ordinal))
        ).scalars().all()


async def _search(client, q, **params):
    r = await client.get("/api/kb/search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_chunking_boundaries_overlap_limit():
    assert search.chunk("") == []
    assert search.chunk("short") == ["short"]
    para = "a" * 2000 + "\n\n" + "b" * 2000
    parts = search.chunk(para)
    assert parts[0] == "a" * 2000 + "\n\n"  # cut on the blank line
    assert parts[1] == para[2002 - 300 :]  # 300 chars of overlap
    flat = "x" * 7000
    parts = search.chunk(flat)
    assert [len(p) for p in parts] == [3000, 3000, 1600]
    assert len(search.chunk("y" * 6_000_000)) == 2000


async def test_embed_job_idempotent_and_reembeds_on_new_revision(client, db):
    w = await _world(client, db)
    doc = await _doc(client, w["org"].id, "Guide", "first body")
    await _drain()
    chunks = await _chunks(doc["id"])
    assert [(c.revision, c.embedding_model) for c in chunks] == [(1, "fake/embed-64")]
    first_ids = [c.id for c in chunks]
    async with SessionLocal() as s:
        await search.embed_document(s, {"document_id": doc["id"]})
        await s.commit()
    assert [c.id for c in await _chunks(doc["id"])] == first_ids  # nothing to do
    await client.put(f"/api/kb/documents/{doc['id']}", json={"base_revision": 1, "body_md": "second body"})
    await _drain()
    chunks = await _chunks(doc["id"])
    assert [(c.revision, c.text) for c in chunks] == [(2, "second body")]


async def test_deleted_document_job_is_a_noop(client, db):
    w = await _world(client, db)
    doc = await _doc(client, w["org"].id, "Gone", "x")
    await client.delete(f"/api/kb/documents/{doc['id']}")
    await _drain()
    jobs = (await db.execute(select(Job))).scalars().all()
    assert [j.status for j in jobs] == [JobStatus.done]


async def test_not_configured_falls_back_to_fts(client, db, real_mode):
    w = await _world(client, db)
    doc = await _doc(client, w["org"].id, "Deploy runbook", "how to deploy the payments service")
    await _drain()
    chunks = await _chunks(doc["id"])
    assert len(chunks) == 1 and chunks[0].embedding_model is None
    body = await _search(client, "payments")
    assert body["semantic"] is False
    assert [r["document_id"] for r in body["results"]] == [doc["id"]]
    assert "payments" in body["results"][0]["snippet"]


async def test_provider_error_during_search_falls_back_to_fts(client, db, real_mode, monkeypatch):
    w = await _world(client, db)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    pid = (await client.post("/api/admin/ai/providers", json={"name": "P", "kind": "openai", "api_key": "k"})).json()["id"]
    await client.put("/api/admin/ai/jobs/embeddings", json={"provider_id": pid, "model": "m"})
    await login(client, w["member"])
    await _doc(client, w["org"].id, "Payments", "payments")

    async def boom(**kw):
        raise RuntimeError("down")

    monkeypatch.setattr(litellm, "aembedding", boom)
    body = await _search(client, "payments")
    assert body["semantic"] is False and len(body["results"]) == 1


async def test_model_change_never_mixes_vectors(client, db):
    w = await _world(client, db)
    doc = await _doc(client, w["org"].id, "Webhooks", "Delivery of webhooks to subscribers.")
    await _drain()
    # a query that full-text search cannot match ("webhook" vs "webhooks"), only the vectors can
    assert [r["document_id"] for r in (await _search(client, "webhook"))["results"]] == [doc["id"]]
    # pretend the chunks came from a previous model
    await db.execute(update(KbChunk).values(embedding_model="old/model"))
    await db.commit()
    body = await _search(client, "webhook")
    assert body["semantic"] is True and body["results"] == []
    # changing the configured model queues a full re-embed
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    pid = (await client.post("/api/admin/ai/providers", json={"name": "P", "kind": "openai"})).json()["id"]
    await client.put("/api/admin/ai/jobs/embeddings", json={"provider_id": pid, "model": "m"})
    kinds = [j.kind for j in (await db.execute(select(Job).where(Job.status == JobStatus.queued))).scalars()]
    assert "kb.reembed_all" in kinds
    await _drain()
    await login(client, w["member"])
    assert {c.embedding_model for c in await _chunks(doc["id"])} == {"fake/embed-64"}
    assert [r["document_id"] for r in (await _search(client, "webhook"))["results"]] == [doc["id"]]


async def test_reembed_all_pages(client, db, monkeypatch):
    w = await _world(client, db)
    monkeypatch.setattr(search, "REEMBED_PAGE", 2)
    ids = [(await _doc(client, w["org"].id, f"D{i}", "x"))["id"] for i in range(5)]
    await _drain()
    await db.execute(update(KbChunk).values(embedding_model="old/model"))
    await db.commit()
    async with SessionLocal() as s:
        from app.jobs import queue

        await queue.enqueue(s, "kb.reembed_all", {})
        await s.commit()
    await _drain()
    for i in ids:
        assert {c.embedding_model for c in await _chunks(i)} == {"fake/embed-64"}


async def test_search_never_returns_unreadable_spaces(client, db):
    w = await _world(client, db)
    secret = await _doc(client, w["team"].id, "Secret roadmap", "roadmap for payments")
    public = await _doc(client, w["org"].id, "Public roadmap", "roadmap")
    await _drain()
    ids = {r["document_id"] for r in (await _search(client, "roadmap"))["results"]}
    assert ids == {secret["id"], public["id"]}
    only_team = await _search(client, "roadmap", space=str(w["team"].id))
    assert [r["document_id"] for r in only_team["results"]] == [secret["id"]]
    await login(client, w["outsider"])
    for q in ("roadmap", "payments", "Secret"):
        assert secret["id"] not in {r["document_id"] for r in (await _search(client, q))["results"]}
    assert (await _search(client, "roadmap", space=str(w["team"].id)))["results"] == []


async def test_hybrid_rrf_orders_exact_title_match_first(client, db):
    w = await _world(client, db)
    filler = "Unrelated text about deployment pipelines and release trains. " * 40
    other = await _doc(client, w["org"].id, "Release notes", filler + "One mention of invoices here.")
    title = await _doc(client, w["org"].id, "Invoices", "How invoices are generated.")
    await _drain()
    results = (await _search(client, "invoices"))["results"]
    assert [r["document_id"] for r in results][:2] == [title["id"], other["id"]]
    assert results[0]["score"] > results[1]["score"]
    assert results[0]["space"]["kind"] == "org" and results[0]["path"] == ""
    assert len(results[1]["snippet"]) <= 300 and "invoices" in results[1]["snippet"]


async def test_query_limits(client, db):
    await _world(client, db)
    assert (await client.get("/api/kb/search", params={"q": ""})).status_code == 422
    assert (await client.get("/api/kb/search", params={"q": "x" * 501})).status_code == 422
    assert (await _search(client, "!!! ''' &&&"))["results"] == []


async def test_embed_failure_retries_then_failed_job_visible(client, db, real_mode, monkeypatch):
    w = await _world(client, db)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    pid = (await client.post("/api/admin/ai/providers", json={"name": "P", "kind": "openai", "api_key": "k"})).json()["id"]
    await client.put("/api/admin/ai/jobs/embeddings", json={"provider_id": pid, "model": "m"})
    await db.execute(update(Job).values(status=JobStatus.done))  # the re-embed sweep is not under test
    await db.commit()

    async def boom(**kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(litellm, "aembedding", boom)
    await login(client, w["member"])
    doc = await _doc(client, w["org"].id, "Doc", "body")
    await db.execute(update(Job).where(Job.kind == "kb.embed").values(max_attempts=2))
    await db.commit()
    await _drain()
    job = (await db.execute(select(Job).where(Job.kind == "kb.embed"))).scalar_one()
    await db.refresh(job)
    assert job.status == JobStatus.queued and job.attempts == 1 and "provider down" in job.last_error
    await db.execute(update(Job).where(Job.id == job.id).values(run_after=job.created_at))
    await db.commit()
    await _drain()
    await login(client, admin)
    failed = (await client.get("/api/admin/jobs", params={"status": "failed"})).json()
    assert [(f["kind"], f["attempts"]) for f in failed] == [("kb.embed", 2)]
    assert "provider down" in failed[0]["last_error"]
    # the document still works and is found by full-text search
    await login(client, w["member"])
    assert [r["document_id"] for r in (await _search(client, "body"))["results"]] == [doc["id"]]

