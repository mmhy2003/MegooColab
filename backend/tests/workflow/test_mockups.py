"""Live mockups (Plan 8 Task 1): show_mockup keeps the turn, a design links to the newest mockup, and nothing new
can be shown while a design awaits approval."""

from sqlalchemy import func, select

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.kb.models import KbDocument, KbFiling
from app.workflow.models import Mockup, RunRole, WorkflowQuestion
from tests.mcp.test_workflow_tools import (
    _connect_only_building,
    _my_task,
    _personal,
    _run_token,
    _set_role,
    _tool,
)
from tests.workflow.test_documents import _decide, _docs
from tests.workflow.test_engine import _events, _finish, _runs, _started

HTML = "<html><body><h1>Layout</h1></body></html>"


async def _count(task_id) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(Mockup).where(Mockup.task_id == task_id))


async def _mockups(task_id) -> list[Mockup]:
    async with SessionLocal() as s:
        rows = await s.execute(select(Mockup).where(Mockup.task_id == task_id).order_by(Mockup.version))
        return list(rows.scalars())


async def test_show_mockup_stores_next_version_and_keeps_the_turn(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    assert _tool(tc, token, "show_mockup", key=b.key, html=HTML, title="Layout A") == (False, {"version": 1})
    assert _tool(tc, token, "show_mockup", key=b.key, html=HTML, title="Layout B") == (False, {"version": 2})
    rows = await _mockups(b.task_id)
    assert [(m.version, m.title, m.choices) for m in rows] == [(1, "Layout A", []), (2, "Layout B", [])]
    async with SessionLocal() as s:
        assert (await s.get(AgentRun, run.id)).status == "running"
        assert await s.scalar(select(func.count()).select_from(WorkflowQuestion)) == 0
    shown = sorted((e.data for e in await _events(b.task_id, "mockup.shown")), key=lambda d: d["version"])
    assert shown == [{"version": 1, "title": "Layout A"}, {"version": 2, "title": "Layout B"}]


async def test_show_mockup_role_and_limits(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    for role in RunRole:
        if role == RunRole.brainstorm:
            continue
        await _set_role(run, role.value, step=1)
        err, text = _tool(tc, token, "show_mockup", key=b.key, html=HTML, title="T")
        assert err and "not_allowed_in_role" in text, role
    await _set_role(run, "brainstorm")
    err, text = _tool(tc, token, "show_mockup", key=b.key, html="x" * (2 * 1024 * 1024 + 1), title="T")
    assert err and "too_large" in text
    err, text = _tool(tc, token, "show_mockup", key=b.key, html=HTML, title="  ")
    assert err and "invalid_mockup" in text
    async with SessionLocal() as s:
        s.add_all(Mockup(task_id=b.task_id, version=n, title=f"m{n}", html=HTML, choices=[]) for n in range(1, 50))
        await s.commit()
    err, out = _tool(tc, token, "ask_human", key=b.key, question="Which?", mockup_html=HTML, mockup_title="Fiftieth")
    assert not err, out
    assert await _count(b.task_id) == 50
    err, text = _tool(tc, token, "show_mockup", key=b.key, html=HTML, title="One too many")
    assert err and "too_many_mockups" in text
    err, text = _tool(tc, token, "ask_human", key=b.key, question="And?", mockup_html=HTML, mockup_title="Too many")
    assert err and "too_many_mockups" in text
    assert await _count(b.task_id) == 50


async def test_show_mockup_refused_while_a_design_is_submitted(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    assert not _tool(tc, token, "show_mockup", key=b.key, html=HTML, title="v1")[0]
    assert not _tool(tc, token, "submit_design", key=b.key, markdown="# Design")[0]
    err, text = _tool(tc, token, "show_mockup", key=b.key, html=HTML, title="sneaky v2")
    assert err and "design_submitted" in text
    assert await _count(b.task_id) == 1


async def test_resubmitted_design_links_the_newest_mockup(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    assert not _tool(tc, token, "show_mockup", key=b.key, html=HTML, title="v1")[0]
    assert not _tool(tc, token, "submit_design", key=b.key, markdown="# Design v1")[0]
    await _finish(b.manager.id, run, "completed", session_id="brain-1")
    assert _decide(tc, b, "design", 1, False, "Bigger header").status_code == 200
    revision = (await _runs(b.task_id))[-1]
    assert revision.workflow_role == "brainstorm" and revision.id != run.id
    token2 = await _run_token(revision)
    assert _tool(tc, token2, "show_mockup", key=b.key, html=HTML, title="v2") == (False, {"version": 2})
    assert not _tool(tc, token2, "submit_design", key=b.key, markdown="# Design v2")[0]
    v1, v2 = await _mockups(b.task_id)
    d1, d2 = await _docs(b.task_id, "design")
    assert (d1.mockup_id, d2.mockup_id) == (v1.id, v2.id)
    listed = tc.get(f"/api/tasks/{b.key}/documents").json()
    assert [d["mockup_id"] for d in listed if d["kind"] == "design"] == [str(v1.id), str(v2.id)]
    assert tc.get(f"/api/tasks/{b.key}/documents/design/2").json()["mockup_id"] == str(v2.id)


async def test_design_without_mockup_has_no_link(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    assert not _tool(tc, token, "submit_design", key=b.key, markdown="# Design")[0]
    await _finish(b.manager.id, run, "completed", session_id="brain-1")
    [doc] = await _docs(b.task_id, "design")
    assert doc.mockup_id is None
    assert _decide(tc, b, "design", 1, True).status_code == 200


async def test_connect_only_show_mockup_in_brainstorm_and_design_only(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    user = b.manager
    key = _my_task(tc, user)["key"]
    token = _personal(tc)
    assert _tool(tc, token, "show_mockup", key=key, html=HTML, title="Mine") == (False, {"version": 1})
    assert not _tool(tc, token, "submit_design", key=key, markdown="# Design")[0]
    err, text = _tool(tc, token, "show_mockup", key=key, html=HTML, title="v2")
    assert err and "design_submitted" in text
    building, token2 = await _connect_only_building(tc, user)
    err, text = _tool(tc, token2, "show_mockup", key=building, html=HTML, title="late")
    assert err and "wrong_stage" in text


async def test_approved_design_files_its_mockup_line(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    token = await _run_token(run)
    assert not _tool(tc, token, "show_mockup", key=b.key, html=HTML, title="Compact")[0]
    assert not _tool(tc, token, "submit_design", key=b.key, markdown="# Design")[0]
    await _finish(b.manager.id, run, "completed", session_id="brain-1")
    assert _decide(tc, b, "design", 1, True).status_code == 200
    [mockup] = await _mockups(b.task_id)
    async with SessionLocal() as s:
        filed = await s.get(KbFiling, (b.task_id, "design"))
        doc = await s.get(KbDocument, filed.document_id)
    assert doc.body_md.endswith(f"\n\n---\nApproved mockup: v1 — Compact (/api/mockups/{mockup.id}/view)")


async def test_a_stale_submitted_design_does_not_block_a_fresh_brainstorm(db, tc_factory):
    """Final review fix: a design left `submitted` by an earlier connect-only workflow (nothing waits on it) must
    not refuse the new agent's mockups."""
    from app.workflow.models import WorkflowDocument

    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    async with SessionLocal() as s:
        s.add(WorkflowDocument(task_id=b.task_id, kind="design", version=1, body_md="# Old", submitted_run_id=None))
        await s.commit()
    token = await _run_token(run)
    assert _tool(tc, token, "show_mockup", key=b.key, html=HTML, title="Fresh") == (False, {"version": 1})
