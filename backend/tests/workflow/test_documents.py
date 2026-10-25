"""Design and plan documents: submit, supersede, approve and reject (Task 8)."""

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.models import User
from app.core.db import SessionLocal
from app.tasks.models import Task
from app.workflow import documents, questions
from app.workflow.models import WorkflowDocument
from tests.agent_runs.test_dispatch import _task
from tests.factories import DEFAULT_PASSWORD
from tests.workflow.test_engine import (
    _board,
    _events,
    _finish,
    _move,
    _runs,
    _started,
    _wf,
)

STEPS = [{"title": f"Do {n}", "detail": f"detail {n}"} for n in (1, 2, 3)]


async def _submit(b, run, kind="design", body="# Doc", steps=None):
    async with SessionLocal() as s:
        task = await s.get(Task, b.task_id)
        doc = await documents.submit(s, run, task, kind, body, steps)
        await s.commit()
        return doc.version


async def _docs(task_id, kind=None) -> list[WorkflowDocument]:
    async with SessionLocal() as s:
        stmt = select(WorkflowDocument).where(WorkflowDocument.task_id == task_id)
        if kind:
            stmt = stmt.where(WorkflowDocument.kind == kind)
        return list((await s.execute(stmt.order_by(WorkflowDocument.version))).scalars())


def _decide(tc, b, kind, version, approve, comment=None):
    body = {"approve": approve, **({"comment": comment} if comment is not None else {})}
    return tc.post(f"/api/tasks/{b.key}/documents/{kind}/{version}/decision", json=body)


async def _design_waiting(db, tc):
    b, run = await _started(db, tc)
    await _submit(b, run)
    await _finish(b.manager.id, run, "completed", session_id="brain-1")
    wf = await _wf(b.task_id)
    assert (wf.stage, wf.status, wf.needs) == ("design", "waiting_human", "design_approval")
    return b, run


async def _plan_waiting(db, tc):
    b, _ = await _design_waiting(db, tc)
    assert _decide(tc, b, "design", 1, True).status_code == 200
    plan_run = (await _runs(b.task_id))[-1]
    assert plan_run.workflow_role == "plan"
    await _submit(b, plan_run, "plan", "# Plan", STEPS)
    await _finish(b.manager.id, plan_run, "completed", session_id="plan-1")
    wf = await _wf(b.task_id)
    assert (wf.stage, wf.status, wf.needs) == ("plan", "waiting_human", "plan_approval")
    return b, plan_run


async def test_design_approval_moves_to_plan_and_enqueues_plan_run(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_waiting(db, tc)
    r = _decide(tc, b, "design", 1, True)
    assert r.status_code == 200, r.text
    assert (r.json()["stage"], r.json()["status"], r.json()["needs"]) == ("plan", "running", None)
    runs = await _runs(b.task_id)
    assert len(runs) == 2
    assert (runs[-1].workflow_role, runs[-1].stage, runs[-1].resume_session_ref) == ("plan", "plan", None)
    [doc] = await _docs(b.task_id)
    assert (doc.status, doc.decided_by) == ("approved", b.manager.id) and doc.decided_at is not None
    [ev] = await _events(b.task_id, "document.approved")
    assert ev.data == {"kind": "design", "version": 1} and ev.actor_user_id == b.manager.id
    listing = tc.get(f"/api/tasks/{b.key}/documents").json()
    assert [(d["kind"], d["version"], d["status"]) for d in listing] == [("design", 1, "approved")]
    assert tc.get(f"/api/tasks/{b.key}/documents/design/1").json()["body_md"] == "# Doc"


async def test_design_rejection_resumes_brainstorm_session_with_comment(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_waiting(db, tc)
    assert _decide(tc, b, "design", 1, False).json()["detail"] == "comment_required"
    r = _decide(tc, b, "design", 1, False, "Needs a rollback section")
    assert r.status_code == 200, r.text
    assert (r.json()["stage"], r.json()["status"]) == ("design", "running")
    new = (await _runs(b.task_id))[-1]
    assert new.workflow_role == "brainstorm" and new.resume_session_ref == "brain-1"
    assert "Needs a rollback section" in new.resume_prompt and "submit_design" in new.resume_prompt
    [doc] = await _docs(b.task_id)
    assert (doc.status, doc.decision_comment) == ("rejected", "Needs a rollback section")
    [ev] = await _events(b.task_id, "document.rejected")
    assert ev.data == {"kind": "design", "version": 1, "comment": "Needs a rollback section"}
    # the revised design is version 2 and waits for approval again
    await _submit(b, new)
    await _finish(b.manager.id, new, "completed")
    assert (await _wf(b.task_id)).needs == "design_approval"
    assert [d.version for d in await _docs(b.task_id)] == [1, 2]


async def test_concurrent_approve_and_reject_one_wins(db, tc_factory, client_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_waiting(db, tc)
    clients = [client_factory(), client_factory()]
    for c in clients:
        r = await c.post("/api/auth/login", json={"email": b.manager.email, "password": DEFAULT_PASSWORD})
        assert r.status_code == 200
    hdr = {"X-Megoo-Client": "web"}
    url = f"/api/tasks/{b.key}/documents/design/1/decision"
    rs = await asyncio.gather(
        clients[0].post(url, json={"approve": True}, headers=hdr),
        clients[1].post(url, json={"approve": False, "comment": "no"}, headers=hdr),
    )
    assert sorted(r.status_code for r in rs) == [200, 409]
    assert [r.json()["detail"] for r in rs if r.status_code == 409] == ["already_decided"]
    assert len(await _runs(b.task_id)) == 2  # the engine advanced once
    approved, rejected = await _events(b.task_id, "document.approved"), await _events(b.task_id, "document.rejected")
    assert len(approved) + len(rejected) == 1


async def test_plan_approval_creates_subtasks_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _plan_waiting(db, tc)
    r = _decide(tc, b, "plan", 1, True)
    assert r.status_code == 200, r.text
    assert (r.json()["stage"], r.json()["current_step"], r.json()["status"]) == ("build", 1, "running")
    again = _decide(tc, b, "plan", 1, True)
    assert again.status_code == 409 and again.json()["detail"] == "already_decided"
    async with SessionLocal() as s:
        subs = (await s.execute(select(Task).where(Task.parent_id == b.task_id).order_by(Task.number))).scalars().all()
        [doc] = (await s.execute(select(WorkflowDocument).where(WorkflowDocument.kind == "plan"))).scalars().all()
        assert [t.title for t in subs] == ["Step 1: Do 1", "Step 2: Do 2", "Step 3: Do 3"]
        assert [t.description_md for t in subs] == ["detail 1", "detail 2", "detail 3"]
        assert all(t.type == "subtask" and t.reporter_id == b.manager.id for t in subs)
        assert len({t.column_id for t in subs}) == 1
        assert [st["subtask_id"] for st in doc.steps] == [str(t.id) for t in subs]
    cols = {c["id"]: c for c in tc.get("/api/projects/PAY/columns").json()}
    assert cols[str(subs[0].column_id)]["category"] == "before"
    last = (await _runs(b.task_id))[-1]
    assert (last.workflow_role, last.step, last.stage) == ("implement", 1, "build")
    assert len(await _runs(b.task_id)) == 3


async def test_plan_rejection_resumes_plan_session(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _plan_waiting(db, tc)
    r = _decide(tc, b, "plan", 1, False, "Split step 2")
    assert r.status_code == 200, r.text
    new = (await _runs(b.task_id))[-1]
    assert new.workflow_role == "plan" and new.resume_session_ref == "plan-1"
    assert "Split step 2" in new.resume_prompt and "submit_plan" in new.resume_prompt
    async with SessionLocal() as s:
        assert (await s.execute(select(Task).where(Task.parent_id == b.task_id))).first() is None


async def test_resubmission_supersedes_old_version(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    assert await _submit(b, run, body="one") == 1
    assert await _submit(b, run, body="two") == 2
    assert [(d.version, d.status) for d in await _docs(b.task_id)] == [(1, "superseded"), (2, "submitted")]
    assert [e.data for e in await _events(b.task_id, "document.submitted")] == [
        {"kind": "design", "version": 1}, {"kind": "design", "version": 2}]
    await _finish(b.manager.id, run, "completed")
    r = _decide(tc, b, "design", 1, True)
    assert r.status_code == 409 and r.json()["detail"] == "already_decided"
    assert _decide(tc, b, "design", 2, True).status_code == 200


HTML = '<html><body><button data-megoo-choice="a">A</button></body></html>'


async def _ask_and_answer(b, run, choice, *, choices=(), mockup_choices=("a", "b")):
    """A question with a mockup, asked by `run` and answered through the real answer path."""
    async with SessionLocal() as s:
        task = await s.get(Task, b.task_id)
        q = await questions.ask(
            s, run, task, "Layout?", list(choices), {"title": "L", "html": HTML, "choices": list(mockup_choices)}
        )
        await s.commit()
        mockup_id, qid = str(q.mockup_id), q.id
    async with SessionLocal() as s:
        await questions.answer(s, await s.get(User, b.manager.id), await s.get(Task, b.task_id), qid, choice, None)
        await s.commit()
    return mockup_id


async def test_design_attaches_chosen_mockup(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    chosen = await _ask_and_answer(b, run, "a")
    # a later mockup question answered with an ordinary choice attaches nothing
    pg = [{"id": "pg", "label": "Postgres", "description": "", "recommended": False}]
    await _ask_and_answer(b, run, "pg", choices=pg, mockup_choices=("x",))
    await _submit(b, run)
    out = tc.get(f"/api/tasks/{b.key}/documents/design/1").json()
    assert out["attached_mockup_ids"] == [chosen]


async def test_design_attaches_nothing_when_a_non_mockup_choice_was_picked(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    pg = [{"id": "pg", "label": "Postgres", "description": "", "recommended": False}]
    await _ask_and_answer(b, run, "pg", choices=pg)
    await _submit(b, run)
    assert tc.get(f"/api/tasks/{b.key}/documents/design/1").json()["attached_mockup_ids"] == []


async def test_plan_requires_steps_and_design_forbids_them(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)

    async def code(kind, body="x", steps=None):
        with pytest.raises(HTTPException) as e:
            async with SessionLocal() as s:
                await documents.submit(s, run, await s.get(Task, b.task_id), kind, body, steps)
        assert e.value.status_code == 422
        return e.value.detail

    assert await code("plan") == "steps_required"
    assert await code("design", steps=STEPS) == "steps_forbidden"
    assert await code("plan", steps=[]) == "invalid_steps"
    assert await code("plan", steps=[{"title": "x"}] * 51) == "invalid_steps"
    assert await code("plan", steps=[{"title": " ", "detail": ""}]) == "invalid_steps"
    assert await code("plan", steps=[{"title": "t" * 201, "detail": ""}]) == "too_large"
    assert await code("plan", steps=[{"title": "t", "detail": "d" * 4001}]) == "too_large"
    assert await code("design", body="x" * 200_001) == "too_large"
    assert await code("design", body="\x00") == "empty_document"
    assert await _docs(b.task_id) == []


async def test_decision_guards(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _submit(b, run)  # submitted, but the run has not ended: the workflow is still running
    r = _decide(tc, b, "design", 1, True)
    assert r.status_code == 409 and r.json()["detail"] == "not_waiting_for_decision"
    assert _decide(tc, b, "design", 9, True).status_code == 404
    await _finish(b.manager.id, run, "completed")
    r = _decide(tc, b, "design", 1, False, "x" * 4001)
    assert r.status_code == 422 and r.json()["detail"] == "too_large"
    assert len(await _runs(b.task_id)) == 1


async def test_deleted_plan_subtask_does_not_break_build(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _plan_waiting(db, tc)
    assert _decide(tc, b, "plan", 1, True).status_code == 200
    async with SessionLocal() as s:
        first = (await s.execute(select(Task).where(Task.parent_id == b.task_id).order_by(Task.number))).scalars().first()
        sub_key = f"PAY-{first.number}"
    assert tc.delete(f"/api/tasks/{sub_key}").status_code == 204
    run = (await _runs(b.task_id))[-1]
    await _finish(b.manager.id, run, "failed")  # the engine re-queues step 1 without the subtask
    last = (await _runs(b.task_id))[-1]
    assert (last.workflow_role, last.step) == ("implement", 1) and last.id != run.id
    out = tc.get(f"/api/tasks/{b.key}/workflow").json()
    assert out["steps_total"] == 3 and out["current_step"] == 1


async def test_concurrent_plan_approvals_create_subtasks_once(db, tc_factory, client_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _plan_waiting(db, tc)
    clients = [client_factory(), client_factory()]
    for c in clients:
        r = await c.post("/api/auth/login", json={"email": b.manager.email, "password": DEFAULT_PASSWORD})
        assert r.status_code == 200
    url = f"/api/tasks/{b.key}/documents/plan/1/decision"
    rs = await asyncio.gather(*(c.post(url, json={"approve": True}) for c in clients))
    assert sorted(r.status_code for r in rs) == [200, 409]
    assert [r.json()["detail"] for r in rs if r.status_code == 409] == ["already_decided"]
    async with SessionLocal() as s:
        subs = (await s.execute(select(Task).where(Task.parent_id == b.task_id))).scalars().all()
    assert len(subs) == len(STEPS)
    assert len([r for r in await _runs(b.task_id) if r.workflow_role == "implement"]) == 1


async def test_plan_subtasks_publish_task_created(db, tc_factory, monkeypatch):
    from app.tasks import service as task_service

    published = []
    real = task_service.publish

    async def spy(db_, event):
        published.append(event)
        await real(db_, event)

    monkeypatch.setattr(task_service, "publish", spy)
    tc = tc_factory(lifespan=True)
    b, _ = await _plan_waiting(db, tc)
    published.clear()
    assert _decide(tc, b, "plan", 1, True).status_code == 200
    async with SessionLocal() as s:
        subs = (await s.execute(select(Task).where(Task.parent_id == b.task_id))).scalars().all()
    created = [e.task_id for e in published if e.type == "task.created"]
    assert sorted(created) == sorted(t.id for t in subs) and len(created) == len(STEPS)


async def test_workflow_refused_on_epic_and_subtask(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    epic = _task(tc, b.agent, title="E", type="epic")
    parent = _task(tc, b.agent, title="P")
    sub = _task(tc, b.agent, title="S", type="subtask", parent_id=parent["id"])
    for t in (epic, sub):
        r = tc.post(f"/api/tasks/{t['key']}/workflow/start")
        assert r.status_code == 422 and r.json()["detail"] == "workflow_not_supported_for_type", t["type"]
        r = _move(tc, t["key"], b.cols["working"])
        assert r.status_code == 422 and r.json()["detail"] == "workflow_not_supported_for_type", t["type"]
    assert tc.get(f"/api/tasks/{epic['key']}").json()["column_id"] != b.cols["working"]["id"]


async def test_type_change_to_epic_refused_while_workflow_active(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    r = tc.patch(f"/api/tasks/{b.key}", json={"type": "epic"})
    assert r.status_code == 409 and r.json()["detail"] == "workflow_active"
    assert tc.get(f"/api/tasks/{b.key}").json()["type"] == b.task["type"]
    # a task whose workflow has not started can change type
    other = _task(tc, b.agent, title="Other")
    assert tc.patch(f"/api/tasks/{other['key']}", json={"type": "epic"}).status_code == 200


async def test_rejection_without_a_stored_session_reaches_the_fresh_prompt(db, tc_factory):
    """I6: with no session to resume, the rejection comment goes into the full prompt, under a heading."""
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _submit(b, run)
    await _finish(b.manager.id, run, "completed")  # no session reported
    assert (await _wf(b.task_id)).needs == "design_approval"
    r = _decide(tc, b, "design", 1, False, "Needs a rollback section")
    assert r.status_code == 200, r.text
    new = (await _runs(b.task_id))[-1]
    assert (new.workflow_role, new.resume_session_ref, new.resume_prompt) == ("brainstorm", None, None)
    tail = new.prompt[new.prompt.index("\n\n## Rejection\n"):]
    assert "Needs a rollback section" in tail and "submit_design" in tail
    assert len(new.prompt) <= 60_000
