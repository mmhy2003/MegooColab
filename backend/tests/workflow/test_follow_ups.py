"""Follow-up tasks a design proposes (MC-81): what the agent submits and what the person approves."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.db import SessionLocal
from app.tasks.models import Task, TaskLink
from app.workflow import follow_ups
from app.workflow.follow_ups import backlink, clean_proposed, clean_reviewed
from tests.agent_runs.test_dispatch import _task
from tests.workflow.test_documents import _decide, _docs, _submit
from tests.workflow.test_engine import _events, _finish, _runs, _started, _wf


def _code(fn, items) -> str:
    with pytest.raises(HTTPException) as e:
        fn(items)
    assert e.value.status_code == 422
    return e.value.detail


def test_clean_proposed():
    assert clean_proposed(None) == []
    assert clean_proposed([]) == []
    assert clean_proposed([
        {"title": "  Phase 2\x00 ", "type": "story", "description_md": "Do\x00 the rest "},
        {"title": "Phase 3"},
    ]) == [
        {"title": "Phase 2", "type": "story", "description_md": "Do the rest ", "task_id": None},
        {"title": "Phase 3", "type": "task", "description_md": "", "task_id": None},
    ]


def test_clean_proposed_refuses():
    ok = {"title": "t", "type": "task", "description_md": ""}
    for bad in (
        {"title": "t"},
        [ok] * 11,
        ["t"],
        [{**ok, "title": "  "}],
        [{**ok, "type": "epic"}],
        [{**ok, "type": "subtask"}],
        [{**ok, "description_md": 3}],
    ):
        assert _code(clean_proposed, bad) == "invalid_follow_ups"
    assert _code(clean_proposed, [{**ok, "title": "t" * 501}]) == "too_large"
    assert _code(clean_proposed, [{**ok, "description_md": "d" * 4001}]) == "too_large"
    assert len(clean_proposed([ok] * 10)) == 10


def test_clean_reviewed():
    ok = {"title": "t", "type": "bug", "description_md": "d", "create": True}
    assert _code(clean_reviewed, [{"title": "t"}]) == "invalid_follow_ups"
    assert _code(clean_reviewed, [{**ok, "create": "yes"}]) == "invalid_follow_ups"
    assert _code(clean_reviewed, [{**ok, "title": " "}]) == "invalid_follow_ups"
    assert _code(clean_reviewed, None) == "invalid_follow_ups"
    assert clean_reviewed([
        {**ok, "title": "B"},
        {**ok, "title": " ", "create": False},
        {**ok, "title": "A", "create": False},
    ]) == [
        {"title": "B", "type": "bug", "description_md": "d", "task_id": None, "create": True},
        {"title": "A", "type": "bug", "description_md": "d", "task_id": None, "create": False},
    ]


# ---- approval creates the ticked tasks (step 4) ----------------------------------------------------------------

PROPOSED = [
    {"title": "Phase 2: refunds", "type": "story", "description_md": "Refund flow."},
    {"title": "Phase 3: reports", "type": "task", "description_md": "Monthly report."},
]


async def _design_with(db, tc, follow_ups=PROPOSED):
    b, run = await _started(db, tc)
    await _submit(b, run, follow_ups=follow_ups)
    await _finish(b.manager.id, run, "completed", session_id="brain-1")
    return b, run


def _approve(tc, b, version, follow_ups):
    return tc.post(f"/api/tasks/{b.key}/documents/design/{version}/decision",
                   json={"approve": True, "follow_ups": follow_ups})


async def _others(task_id) -> list[Task]:
    """Every task of the board except the originating one, oldest first."""
    async with SessionLocal() as s:
        rows = await s.execute(select(Task).where(Task.id != task_id).order_by(Task.number))
        return list(rows.scalars())


def _ticked(*entries):
    return [{**e, "create": c} for e, c in entries]


async def test_approval_creates_ticked_tasks(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_with(db, tc)
    docs = {"title": "Docs", "type": "bug", "description_md": "", "create": True}
    r = _approve(tc, b, 1, [*_ticked((PROPOSED[0], True), (PROPOSED[1], False)), docs])
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "plan"

    phase2, docs_task = await _others(b.task_id)
    assert [(t.title, t.type) for t in (phase2, docs_task)] == [("Phase 2: refunds", "story"), ("Docs", "bug")]
    first = min((c for c in tc.get("/api/projects/PAY/columns").json() if c["category"] == "before"),
                key=lambda c: c["position"])
    project_key, number = b.key.split("-")
    tail = backlink(project_key, int(number), 1)
    for t in (phase2, docs_task):
        assert t.assignee_user_id is None and t.assignee_agent_id is None
        assert t.reporter_id == b.manager.id
        assert str(t.column_id) == first["id"]
        assert t.description_md.endswith(tail)
    assert phase2.description_md == f"Refund flow.\n\n{tail}"
    assert docs_task.description_md == tail

    async with SessionLocal() as s:
        links = (await s.execute(select(TaskLink).where(TaskLink.source_id == b.task_id))).scalars().all()
    assert sorted((str(link.target_id), link.kind) for link in links) == sorted(
        (str(t.id), "relates") for t in (phase2, docs_task)
    )
    events = await _events(b.task_id, "follow_up_created")
    assert sorted((e.data for e in events), key=lambda d: d["title"]) == [
        {"key": f"PAY-{docs_task.number}", "title": "Docs", "task_id": str(docs_task.id), "type": "bug",
         "design_version": 1},
        {"key": f"PAY-{phase2.number}", "title": "Phase 2: refunds", "task_id": str(phase2.id), "type": "story",
         "design_version": 1},
    ]
    assert {e.actor_user_id for e in events} == {b.manager.id}

    [doc] = await _docs(b.task_id, "design")
    assert doc.status == "approved"
    assert doc.follow_ups == [
        {**PROPOSED[0], "task_id": str(phase2.id)},
        {**PROPOSED[1], "task_id": None},
        {"title": "Docs", "type": "bug", "description_md": "", "task_id": str(docs_task.id)},
    ]


async def test_tasks_go_into_the_epic(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_with(db, tc)
    epic = _task(tc, b.agent, title="E", type="epic")
    assert tc.patch(f"/api/tasks/{b.key}", json={"parent_id": epic["id"]}).status_code == 200
    r = _approve(tc, b, 1, _ticked((PROPOSED[0], True), (PROPOSED[1], True)))
    assert r.status_code == 200, r.text
    created = [t for t in await _others(b.task_id) if str(t.id) != epic["id"]]
    assert len(created) == 2
    assert {str(t.parent_id) for t in created} == {epic["id"]}


async def test_follow_ups_required_and_nothing_sent(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_with(db, tc)
    r = _decide(tc, b, "design", 1, True)
    assert r.status_code == 422 and r.json()["detail"] == "follow_ups_required"
    [doc] = await _docs(b.task_id, "design")
    assert doc.status == "submitted"
    assert (await _wf(b.task_id)).needs == "design_approval"

    # a version proposing none, approved with no list, approves as before
    run = (await _runs(b.task_id))[-1]
    await _submit(b, run)
    r = _decide(tc, b, "design", 2, True)
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "plan"
    assert await _others(b.task_id) == []
    assert await _events(b.task_id, "follow_up_created") == []


async def test_rejection_and_superseded_create_nothing(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_with(db, tc)
    r = tc.post(f"/api/tasks/{b.key}/documents/design/1/decision", json={
        "approve": False, "comment": "Split differently", "follow_ups": _ticked((PROPOSED[0], True)),
    })
    assert r.status_code == 200, r.text
    assert await _others(b.task_id) == []
    [v1] = await _docs(b.task_id, "design")
    assert v1.follow_ups == [{**e, "task_id": None} for e in PROPOSED]  # the agent's list, untouched

    revision = (await _runs(b.task_id))[-1]
    await _submit(b, revision, follow_ups=PROPOSED)  # v2 proposes them again...
    await _submit(b, revision)  # ...and v3, which proposes none, supersedes it
    await _finish(b.manager.id, revision, "completed")
    r = _decide(tc, b, "design", 3, True)
    assert r.status_code == 200, r.text
    assert [d.status for d in await _docs(b.task_id, "design")] == ["rejected", "superseded", "approved"]
    assert await _others(b.task_id) == []
    assert await _events(b.task_id, "follow_up_created") == []


async def test_failure_rolls_back_the_approval(db, tc_factory, monkeypatch):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_with(db, tc)
    calls = 0
    real = follow_ups.create_task

    async def flaky(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HTTPException(422, "invalid_parent")
        return await real(*args, **kwargs)

    monkeypatch.setattr(follow_ups, "create_task", flaky)
    r = _approve(tc, b, 1, _ticked((PROPOSED[0], True), (PROPOSED[1], True)))
    assert r.status_code == 422 and r.json()["detail"] == "invalid_parent"
    [doc] = await _docs(b.task_id, "design")
    assert doc.status == "submitted"
    assert await _others(b.task_id) == []
    assert await _events(b.task_id, "follow_up_created") == []
    assert (await _wf(b.task_id)).needs == "design_approval"


async def test_invalid_reviewed_list_through_the_endpoint(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _design_with(db, tc)
    r = _approve(tc, b, 1, _ticked(*[(PROPOSED[0], True)] * 11))
    assert r.status_code == 422 and r.json()["detail"] == "invalid_follow_ups"
    [doc] = await _docs(b.task_id, "design")
    assert doc.status == "submitted"
    assert await _others(b.task_id) == []
