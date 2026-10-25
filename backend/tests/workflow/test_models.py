import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.tasks.models import Task
from app.workflow.models import DocKind, TaskWorkflow, WorkflowDocument
from tests.factories import login, make_project, make_user


async def _task(client, title="t"):
    r = await client.post("/api/projects/PAY/tasks", json={"title": title, "type": "task"})
    assert r.status_code == 201, r.text
    return r.json()


async def test_project_workflow_settings_defaults_and_patch(client, client_factory, db):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)  # client is logged in as the project manager
    got = (await client.get("/api/projects/PAY")).json()
    assert got["finishing_option"] == "pull_request"
    assert got["require_human_code_review"] is False
    assert got["commit_docs_to_repo"] is False

    r = await client.patch(
        "/api/projects/PAY",
        json={"finishing_option": "keep_branch", "require_human_code_review": True, "commit_docs_to_repo": True},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["finishing_option"], r.json()["require_human_code_review"], r.json()["commit_docs_to_repo"]) == (
        "keep_branch", True, True)
    assert (await client.patch("/api/projects/PAY", json={"finishing_option": "bogus"})).status_code == 422

    other = client_factory()
    await login(other, member)
    denied = await other.patch("/api/projects/PAY", json={"commit_docs_to_repo": False})
    assert denied.status_code == 403
    assert (await client.get("/api/projects/PAY")).json()["commit_docs_to_repo"] is True


async def test_task_out_has_null_workflow_by_default(client, db):
    await make_project(client, db, "PAY")
    t = await _task(client)
    assert t["workflow"] is None
    listed = (await client.get("/api/projects/PAY/tasks")).json()
    items = listed["items"] if isinstance(listed, dict) else listed
    assert items[0]["workflow"] is None


async def test_task_out_includes_workflow_and_steps_total(client, db):
    await make_project(client, db, "PAY")
    t = await _task(client)
    t2 = await _task(client, "other")
    db.add(TaskWorkflow(task_id=uuid.UUID(t["id"]), current_step=1))
    steps = [{"title": f"s{i}", "detail": "", "subtask_id": None} for i in range(3)]
    db.add(WorkflowDocument(task_id=uuid.UUID(t["id"]), kind=DocKind.plan, version=1, body_md="p", steps=steps[:1], status="approved"))
    db.add(WorkflowDocument(task_id=uuid.UUID(t["id"]), kind=DocKind.plan, version=2, body_md="p", steps=steps, status="approved"))
    db.add(WorkflowDocument(task_id=uuid.UUID(t["id"]), kind=DocKind.plan, version=3, body_md="p", steps=steps[:2], status="submitted"))
    await db.commit()
    got = (await client.get(f"/api/tasks/{t['key']}")).json()["workflow"]
    assert got == {
        "driver": "runner", "stage": "brainstorm", "status": "idle", "needs": None,
        "enforcement": "enforced", "current_step": 1, "steps_total": 3, "escalation_reason": None,
    }
    assert (await client.get(f"/api/tasks/{t2['key']}")).json()["workflow"] is None


async def test_document_version_unique(client, db):
    await make_project(client, db, "PAY")
    t = await _task(client)
    db.add(WorkflowDocument(task_id=uuid.UUID(t["id"]), kind=DocKind.design, version=1, body_md="a"))
    await db.commit()
    db.add(WorkflowDocument(task_id=uuid.UUID(t["id"]), kind=DocKind.design, version=1, body_md="b"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    db.add(WorkflowDocument(task_id=uuid.UUID(t["id"]), kind=DocKind.plan, version=1, body_md="c"))
    await db.commit()


async def test_workflow_deleted_with_task(client, db):
    await make_project(client, db, "PAY")
    t = await _task(client)
    db.add(TaskWorkflow(task_id=uuid.UUID(t["id"])))
    db.add(WorkflowDocument(task_id=uuid.UUID(t["id"]), kind=DocKind.design, version=1, body_md="a"))
    await db.commit()
    assert (await client.delete(f"/api/tasks/{t['key']}")).status_code == 204
    db.expire_all()
    assert (await db.execute(select(func.count()).select_from(TaskWorkflow))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(WorkflowDocument))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(Task))).scalar_one() == 0


async def test_in_place_edits_to_jsonb_columns_persist(client, db):
    await make_project(client, db, "PAY")
    t = await _task(client)
    tid = uuid.UUID(t["id"])
    db.add(TaskWorkflow(task_id=tid))
    db.add(WorkflowDocument(task_id=tid, kind=DocKind.plan, version=1, body_md="p", steps=[]))
    await db.commit()

    wf = await db.get(TaskWorkflow, tid)
    wf.sessions["implement:1"] = "s"
    doc = (await db.execute(select(WorkflowDocument).where(WorkflowDocument.task_id == tid))).scalar_one()
    doc.steps.append({"title": "a", "detail": "", "subtask_id": None})
    await db.commit()
    db.expire_all()

    assert (await db.get(TaskWorkflow, tid)).sessions == {"implement:1": "s"}
    doc = (await db.execute(select(WorkflowDocument).where(WorkflowDocument.task_id == tid))).scalar_one()
    assert [s["title"] for s in doc.steps] == ["a"]
