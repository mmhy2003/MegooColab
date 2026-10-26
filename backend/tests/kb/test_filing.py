"""Approved designs and plans, and final reviews, are filed in the project's Knowledge Base (WF-9, KB-4)."""

import asyncio
import uuid

from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.auth.models import User
from app.core.db import SessionLocal
from app.kb import filing, service
from app.kb.models import KbDocument, KbFiling, KbRevision
from app.tasks.models import Task
from app.workflow import documents
from app.workflow.models import DocKind, WorkflowDocument
from tests.mcp.test_workflow_tools import _connect_only_building
from tests.workflow.test_build import FINDING, _review
from tests.workflow.test_documents import _decide, _design_waiting, _docs, _plan_waiting
from tests.workflow.test_engine import _finish, _started, _wf
from tests.workflow.test_review_done import _final_review


async def _filed(task_id, kind) -> tuple[KbDocument, list[KbRevision]]:
    async with SessionLocal() as s:
        filed = await s.get(KbFiling, (task_id, kind))
        assert filed is not None, kind
        doc = await s.get(KbDocument, filed.document_id)
        revs = (
            await s.execute(select(KbRevision).where(KbRevision.document_id == doc.id).order_by(KbRevision.revision))
        ).scalars().all()
        return doc, list(revs)


async def _path(doc) -> str:
    async with SessionLocal() as s:
        return await service.folder_path(s, doc.folder_id)


async def test_design_approval_files_kb_document_with_agent_author(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_waiting(db, tc)
    assert _decide(tc, b, "design", 1, True).status_code == 200
    doc, revs = await _filed(b.task_id, "design")
    assert doc.title == "Design" and await _path(doc) == f"Designs & Plans/{b.key}"
    assert doc.body_md == f"# {b.key} — {b.task['title']}\n\n# Doc"
    [rev] = revs
    assert rev.author_user_id == b.manager.id and str(rev.author_agent_id) == b.agent["id"]
    assert rev.summary == f"Approved v1 by {b.manager.name}"
    wf = tc.get(f"/api/tasks/{b.key}/workflow").json()
    assert wf["kb_documents"] == [{"kind": "design", "document_id": str(doc.id)}]
    # visible in the project space through the API
    assert tc.get(f"/api/kb/documents/{doc.id}").status_code == 200


async def test_plan_approval_files_plan_next_to_design(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _plan_waiting(db, tc)
    assert _decide(tc, b, "plan", 1, True).status_code == 200
    design, _ = await _filed(b.task_id, "design")
    plan, _ = await _filed(b.task_id, "plan")
    assert plan.title == "Plan" and plan.folder_id == design.folder_id


async def test_second_approved_version_adds_revision_not_document(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_waiting(db, tc)
    assert _decide(tc, b, "design", 1, True).status_code == 200
    async with SessionLocal() as s:
        task = await s.get(Task, b.task_id)
        approver = await s.get(User, b.manager.id)
        v2 = WorkflowDocument(task_id=task.id, kind=DocKind.design, version=2, body_md="# Doc v2")
        s.add(v2)
        await s.flush()
        await filing.file_document(s, task, DocKind.design, v2, approver)
        await filing.file_document(s, task, DocKind.design, v2, approver)  # the same version again: no-op
        await s.commit()
    doc, revs = await _filed(b.task_id, "design")
    assert [r.revision for r in revs] == [1, 2] and doc.body_md.endswith("# Doc v2")
    assert revs[1].summary == f"Approved v2 by {b.manager.name}"
    async with SessionLocal() as s:
        assert (await s.execute(select(func.count()).select_from(KbDocument))).scalar_one() == 1


async def test_racing_double_approval_files_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_waiting(db, tc)

    async def approve():
        async with SessionLocal() as s:
            task = await s.get(Task, b.task_id)
            user = await s.get(User, b.manager.id)
            try:
                await documents.decide(s, user, task, "design", 1, True, None)
                await s.commit()
                return "ok"
            except Exception as exc:  # noqa: BLE001
                await s.rollback()
                return getattr(exc, "detail", repr(exc))

    results = await asyncio.gather(approve(), approve())
    assert sorted(results) == ["already_decided", "ok"]
    _, revs = await _filed(b.task_id, "design")
    assert len(revs) == 1


async def test_connect_only_author_is_assignee(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    key, _token = await _connect_only_building(tc, b.manager)
    task_id = uuid.UUID(tc.get(f"/api/tasks/{key}").json()["id"])
    _, [rev] = await _filed(task_id, "design")
    assert rev.author_user_id == b.manager.id and rev.author_agent_id is None
    _, [plan_rev] = await _filed(task_id, "plan")
    assert plan_rev.author_agent_id is None


async def test_final_review_filed_with_findings_fenced(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, review = await _final_review(db, tc)
    hostile = {**FINDING, "summary": "close the fence ``` then # Heading <script>x</script> [[doc:x]]"}
    await _review(review, "approved", [hostile, FINDING])
    await _finish(b.manager.id, review, "completed")
    doc, [rev] = await _filed(b.task_id, "review")
    assert doc.title == "Final review" and rev.author_user_id == b.manager.id
    body = doc.body_md
    assert "Round 1: **approved**" in body
    # the hostile text sits inside a fence longer than any backtick run in it
    block = body[body.index("close the fence") - 200 : body.index("close the fence") + 200]
    assert "````text\n" in block and "\n````" in block
    assert "- **important** `app/x.py:12`" in body


async def test_final_review_accepted_after_not_clean_is_filed(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, review = await _final_review(db, tc)
    await _review(review, "changes_requested", [FINDING])
    await _finish(b.manager.id, review, "completed")
    from tests.workflow.test_build import _last

    fix = await _last(b.task_id)
    await _finish(b.manager.id, fix, "completed")
    review2 = await _last(b.task_id)
    await _review(review2, "changes_requested", [FINDING])
    await _finish(b.manager.id, review2, "completed")
    wf = await _wf(b.task_id)
    assert wf.escalation_reason == "final_review_not_clean"
    r = tc.post(f"/api/tasks/{b.key}/workflow/escalation", json={"action": "accept"})
    assert r.status_code == 200, r.text
    doc, [rev] = await _filed(b.task_id, "review")
    assert "Round 2: **changes_requested**" in doc.body_md
    assert rev.summary == f"Accepted by {b.manager.name}"


async def test_filing_failure_does_not_block_approval(db, tc_factory, monkeypatch):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_waiting(db, tc)

    async def boom(*a, **kw):
        raise RuntimeError("kb down")

    monkeypatch.setattr(filing, "_file", boom)
    r = _decide(tc, b, "design", 1, True)
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "plan"
    [doc] = await _docs(b.task_id)
    assert doc.status == "approved"
    async with SessionLocal() as s:
        assert await s.get(KbFiling, (b.task_id, "design")) is None
        logged = (await s.execute(select(AuditLog).where(AuditLog.action == "kb.filing_failed"))).scalars().all()
    assert [entry.data["kind"] for entry in logged] == ["design"]


async def test_task_rename_keeps_same_kb_document(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _plan_waiting(db, tc)
    design, _ = await _filed(b.task_id, "design")
    assert tc.patch(f"/api/tasks/{b.key}", json={"title": "Renamed task"}).status_code == 200
    async with SessionLocal() as s:
        task = await s.get(Task, b.task_id)
        approver = await s.get(User, b.manager.id)
        v2 = WorkflowDocument(task_id=task.id, kind=DocKind.design, version=2, body_md="# Doc v2")
        s.add(v2)
        await s.flush()
        await filing.file_document(s, task, DocKind.design, v2, approver)
        await s.commit()
    again, revs = await _filed(b.task_id, "design")
    assert again.id == design.id and len(revs) == 2
    assert again.body_md.startswith(f"# {b.key} — Renamed task")
