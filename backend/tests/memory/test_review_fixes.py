"""Regression tests for the Plan 5 final review findings."""

import asyncio
import types
import uuid

import litellm
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.ai import client as ai
from app.auth.models import Role
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.jobs.models import Job, JobStatus
from app.kb import access as kb_access
from app.kb.models import KbDocument
from app.memory import answer as answering
from app.memory import dream, extract
from app.memory import router as mem_router
from app.memory.models import (
    ConclusionStatus,
    MemCard,
    MemConclusion,
    MemPremise,
    MemSourceState,
    ScopeKind,
)
from app.memory.search import search_conclusions
from app.tasks.models import Comment, Task
from tests.factories import login, make_project, make_user
from tests.memory.test_dream import (
    _active,
    _dream,
    calls,  # noqa: F401 - fixture
)
from tests.memory.test_search import _add


async def _extract(kind, sid):
    async with SessionLocal() as s:
        await extract.extract(s, {"source_kind": kind, "source_id": str(sid)})
        await s.commit()


# -- C1: moving a KB document re-scopes what was learned from it ---------------------------------------


async def test_kb_move_rescopes_learned_facts(client, db):
    member = await make_user(db)
    project, _m, _t = await make_project(client, db, "SEC", member)
    outsider = await make_user(db)
    org_space = await kb_access.org_space(db)
    doc = KbDocument(id=uuid.uuid4(), space_id=org_space.id, title="Secret plan",
                     body_md="The acquisition of Contoso closes in March next year.")
    db.add(doc)
    await db.commit()
    await _extract("kb_document", doc.id)
    [row] = (await db.execute(select(MemConclusion).where(MemConclusion.source_id == doc.id))).scalars().all()
    row.pinned = True  # even a pinned fact must not stay readable by everyone
    derived = await _add(db, "Contoso deal closes next spring")
    db.add(MemPremise(conclusion_id=derived.id, premise_id=row.id))
    org_card = MemCard(entity_id=row.entity_id, scope_kind=ScopeKind.org, summary_md="Contoso closes in March",
                       conclusion_ids=[str(row.id), str(derived.id)])
    db.add(org_card)
    await db.commit()

    doc.space_id = (await kb_access.space_for_project(db, project["id"])).id
    await db.commit()
    await _extract("kb_document", doc.id)

    assert [r.text for r in await search_conclusions(db, outsider, "acquisition Contoso deal")] == []
    await db.refresh(derived)
    await db.refresh(org_card)
    assert derived.status == ConclusionStatus.superseded and org_card.summary_md == ""
    seen = [r.text for r in await search_conclusions(db, member, "acquisition Contoso")]
    assert seen == ["The acquisition of Contoso closes in March next year"]
    [new] = [r for r in await search_conclusions(db, member, "acquisition Contoso")]
    assert (new.scope_kind, str(new.scope_project_id)) == (ScopeKind.project, project["id"])


# -- C2: a deleted derived conclusion is not re-derived ------------------------------------------------


async def test_deleted_induction_does_not_come_back(db, calls):  # noqa: F811
    admin = await make_user(db, role=Role.admin)
    a = await _add(db, "Webhooks retry billing three times")
    b = await _add(db, "Refunds go through billing service")
    a.source_kind, a.source_id = "comment", uuid.uuid4()
    b.source_kind, b.source_id = "kb_document", uuid.uuid4()
    await db.commit()
    await _dream()
    target = next(r for t, r in (await _active(db)).items() if t.startswith("Pattern:"))
    async with SessionLocal() as s:
        await mem_router.delete_conclusion(target.id, admin, s)
        await s.commit()
    await _dream()
    async with SessionLocal() as s:
        assert target.text not in await _active(s)


# -- I1/I2/I3: dreaming commits per pair, is bounded, and fails visibly ---------------------------------


async def test_dream_commits_per_pair_and_caps_pairs(client, db, calls, monkeypatch):  # noqa: F811
    monkeypatch.setattr(dream, "PAIRS_PER_RUN", 2)
    for key in ("AAA", "BBB", "CCC"):
        p, _, _ = await make_project(client, db, key)
        await _add(db, f"Fact for {key} project", scope=(ScopeKind.project, uuid.UUID(p["id"])))
    run = await _dream()
    assert run.stats["pairs"] == 2 and run.stats["cards"] == 2
    run = await _dream()
    assert run.stats["pairs"] == 1


async def test_dream_all_pairs_failing_marks_run_failed(db, monkeypatch):
    await _add(db, "One fact about releases")
    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "dreaming", lambda m: "garbage")
    run = await _dream()
    assert run.status == "failed" and "AiBadOutput" in run.error and run.stats["failed_pairs"] == 1


async def test_dream_aborts_after_consecutive_failures(client, db, monkeypatch):
    monkeypatch.setattr(dream, "MAX_CONSECUTIVE_FAILURES", 2)
    for key in ("AAA", "BBB", "CCC", "DDD"):
        p, _, _ = await make_project(client, db, key)
        await _add(db, f"Fact for {key}", scope=(ScopeKind.project, uuid.UUID(p["id"])))
    seen = []

    def boom(m):
        seen.append(m)
        raise RuntimeError("provider down")

    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "dreaming", boom)
    run = await _dream()
    assert len(seen) == 2 and run.status == "failed" and "provider down" in run.error


async def test_dreaming_asks_for_8000_tokens_and_truncation_is_bad_output(client, db, monkeypatch):
    await _add(db, "One fact about releases")
    monkeypatch.setattr(get_settings(), "ai_fake", False)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    pid = (await client.post("/api/admin/ai/providers", json={"name": "P", "kind": "openai", "api_key": "k"})).json()["id"]
    await client.put("/api/admin/ai/jobs/dreaming", json={"provider_id": pid, "model": "m"})
    seen = {}

    async def cut(**kw):
        seen.update(kw)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"card": "x'), finish_reason="length")],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    monkeypatch.setattr(litellm, "acompletion", cut)
    run = await _dream()
    assert seen["max_tokens"] == dream.MAX_TOKENS == 8000 and seen["max_retries"] == 0
    assert run.status == "failed" and "truncated" in run.error


# -- I4: answering is capped at 60 s in total ---------------------------------------------------------


async def test_answer_total_timeout(client, db, monkeypatch):
    member = await make_user(db)
    await _add(db, "Webhooks are signed with HMAC")
    monkeypatch.setattr(answering, "ANSWER_TIMEOUT_SECONDS", 0.2)

    async def slow(*a, **kw):
        await asyncio.sleep(5)

    monkeypatch.setattr(ai, "complete", slow)
    start = asyncio.get_running_loop().time()
    with pytest.raises(HTTPException) as e:
        await answering.answer(db, member, "How are webhooks signed?")
    assert (e.value.status_code, e.value.detail) == (502, "memory_unavailable")
    assert asyncio.get_running_loop().time() - start < 2


# -- I5: the LLM Test prompt names JSON (OpenAI's json_object mode requires it) ------------------------


async def test_llm_test_prompt_mentions_json(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_fake", False)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    pid = (await client.post("/api/admin/ai/providers", json={"name": "P", "kind": "openai", "api_key": "k"})).json()["id"]
    await client.put("/api/admin/ai/jobs/extraction", json={"provider_id": pid, "model": "m"})
    seen = {}

    async def ok(**kw):
        seen.update(kw)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"ok": true}'), finish_reason="stop")],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    monkeypatch.setattr(litellm, "acompletion", ok)
    assert (await client.post("/api/admin/ai/jobs/extraction/test")).json()["ok"] is True
    assert "json" in seen["messages"][-1]["content"].lower()


# -- I6: deleting or correcting clears cards that summarised it ----------------------------------------


async def test_delete_and_correct_clear_cards_using_the_conclusion(client, db):
    admin = await make_user(db, role=Role.admin)
    a = await _add(db, "Secret staging key is abc")
    b = await _add(db, "Releases ship weekly")
    card = MemCard(entity_id=a.entity_id, scope_kind=ScopeKind.org, summary_md="Key abc; weekly",
                   conclusion_ids=[str(a.id), str(b.id)])
    db.add(card)
    await db.commit()
    await login(client, admin)
    assert (await client.delete(f"/api/memory/conclusions/{a.id}")).status_code == 204
    await db.refresh(card)
    assert card.summary_md == ""
    detail = (await client.get(f"/api/memory/entities/{a.entity_id}")).json()
    assert detail["cards"] == []
    card.summary_md = "weekly"
    await db.commit()
    await client.post(f"/api/memory/conclusions/{b.id}/correct", json={"text": "Releases ship every two weeks"})
    await db.refresh(card)
    assert card.summary_md == ""


# -- I7: dreaming never replaces a human correction ----------------------------------------------------


async def test_dream_never_replaces_corrections(db, calls):  # noqa: F811
    a = await _add(db, "Deploys run nightly")
    b = await _add(db, "Deploys run nightly")
    a.kind = "correction"
    await db.commit()
    await _dream()
    await db.refresh(a)
    await db.refresh(b)
    assert a.status == ConclusionStatus.active and b.status == ConclusionStatus.superseded


# -- I8: deleting a source forgets what was learned from it --------------------------------------------


async def test_deleted_comment_is_forgotten(client, db):
    project, _manager, _team = await make_project(client, db, "PAY")
    await client.post("/api/projects/PAY/tasks", json={"title": "Go", "type": "task"})
    c = (await client.post("/api/tasks/PAY-1/comments", json={"body_md": "The staging key is abc123 for everyone."})).json()
    await _extract("comment", c["id"])
    [row] = (await db.execute(select(MemConclusion).where(MemConclusion.source_id == uuid.UUID(c["id"])))).scalars().all()
    card = MemCard(entity_id=row.entity_id, scope_kind=ScopeKind.project, scope_project_id=uuid.UUID(project["id"]),
                   summary_md="key abc123", conclusion_ids=[str(row.id)])
    db.add(card)
    await db.commit()
    assert (await client.delete(f"/api/comments/{c['id']}")).status_code == 204
    kinds = [j.kind for j in (await db.execute(select(Job).where(Job.status == JobStatus.queued))).scalars()]
    assert "mem.forget" in kinds
    async with SessionLocal() as s:
        await extract.forget_missing(s, {})
        await s.commit()
    await db.refresh(row)
    await db.refresh(card)
    assert row.status == ConclusionStatus.superseded and card.summary_md == ""
    assert await db.get(MemSourceState, ("comment", uuid.UUID(c["id"]))) is None


async def test_deleted_task_and_kb_document_queue_forget(client, db):
    await make_project(client, db, "PAY")
    await client.post("/api/projects/PAY/tasks", json={"title": "Go", "type": "task"})
    await db.execute(update(Job).values(status=JobStatus.done))
    await db.commit()
    assert (await client.delete("/api/tasks/PAY-1")).status_code == 204
    kinds = [j.kind for j in (await db.execute(select(Job).where(Job.status == JobStatus.queued))).scalars()]
    assert kinds == ["mem.forget"]
    await db.execute(update(Job).values(status=JobStatus.done))
    await db.commit()
    org = await kb_access.org_space(db)
    await db.commit()
    doc = (await client.post(f"/api/kb/spaces/{org.id}/documents", json={"title": "T", "body_md": "b"})).json()
    await db.execute(update(Job).values(status=JobStatus.done))
    await db.commit()
    await client.delete(f"/api/kb/documents/{doc['id']}")
    kinds = [j.kind for j in (await db.execute(select(Job).where(Job.status == JobStatus.queued))).scalars()]
    assert kinds == ["mem.forget"]


# -- I9: configuring extraction learns what already exists ---------------------------------------------


async def test_configuring_extraction_backfills_existing_sources(client, db, monkeypatch):
    _project, manager, _ = await make_project(client, db, "PAY")
    r = await client.post("/api/projects/PAY/tasks", json={"title": "Old task", "type": "task"})
    task = await db.get(Task, uuid.UUID(r.json()["id"]))
    c = Comment(task_id=task.id, author_user_id=manager.id, body_md="Old comment")
    db.add(c)
    await db.execute(Job.__table__.delete())
    await db.commit()
    monkeypatch.setattr(extract, "BACKFILL_PAGE", 1)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    pid = (await client.post("/api/admin/ai/providers", json={"name": "P", "kind": "openai"})).json()["id"]
    await client.put("/api/admin/ai/jobs/extraction", json={"provider_id": pid, "model": "m"})
    assert [j.kind for j in (await db.execute(select(Job))).scalars()] == ["mem.backfill"]
    for _ in range(10):  # chained pages
        async with SessionLocal() as s:
            pending = (await s.execute(select(Job).where(Job.kind == "mem.backfill", Job.status == JobStatus.queued))).scalars().first()
            if pending is None:
                break
            pending.status = JobStatus.done
            await extract.backfill(s, dict(pending.payload))
            await s.commit()
    keys = sorted(j.dedupe_key for j in (await db.execute(select(Job).where(Job.kind == "mem.extract"))).scalars())
    assert keys == sorted([f"mem.extract:task:{task.id}", f"mem.extract:comment:{c.id}"])

