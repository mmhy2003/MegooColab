"""Plan 6 follow-ups: asking under concurrency, run tokens scoped to their task's questions, one routing pass per
free slot, and whether the Q&A document is readable."""

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.a2a import routing, service
from app.a2a.models import Question
from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.projects.models import Project
from tests.a2a.test_answer import CITE
from tests.a2a.test_ask import _ask
from tests.a2a.test_ask import _world as _ask_world
from tests.a2a.test_routing import _agent, _cleanup, _online, _world
from tests.mcp.test_a2a_tools import _target
from tests.mcp.test_workflow_tools import _personal, _run_token, _tool
from tests.workflow.test_engine import _started


async def _ask_in_own_session(asker, body="How is sync signed?"):
    async with SessionLocal() as s:
        user = await s.get(type(asker), asker.id)
        q, _ = await service.ask(s, user, project_key="QBB", body=body)
        await s.commit()
        return q.id


async def test_ask_does_not_hold_project_lock_during_suggestions(client, db, monkeypatch):
    _m1, _m2, asker = await _world(client, db)
    project_id = (await db.execute(select(Project.id).where(Project.key == "QBB"))).scalar_one()
    real = service.suggest
    seen = []

    async def probing(session, user, pid, text_):
        async with SessionLocal() as other:  # another asker's transaction must not wait on this one
            await other.execute(text("SET LOCAL lock_timeout = '200ms'"))
            await other.execute(select(Project.id).where(Project.id == project_id).with_for_update())
            seen.append("free")
        return await real(session, user, pid, text_)

    monkeypatch.setattr(service, "suggest", probing)
    await _ask_in_own_session(asker)
    await _ask_in_own_session(asker, body="Second?")
    assert seen == ["free", "free"]
    numbers = (await db.execute(select(Question.number).order_by(Question.number))).scalars().all()
    assert numbers == [1, 2]


async def test_open_question_cap_holds_under_concurrency(client, db):
    _m1, _m2, asker = await _world(client, db)

    async def one(i):
        try:
            await _ask_in_own_session(asker, body=f"Question {i}?")
            return "ok"
        except HTTPException as e:
            return e.detail

    results = await asyncio.gather(*(one(i) for i in range(service.OPEN_QUESTION_CAP + 1)))
    assert sorted(results) == ["ok"] * service.OPEN_QUESTION_CAP + ["too_many_open_questions"]
    assert await db.scalar(select(func.count()).select_from(Question)) == service.OPEN_QUESTION_CAP


async def test_task_run_token_reads_only_its_tasks_questions(db, tc_factory, client_factory):
    tc = tc_factory(lifespan=True)
    _b, run = await _started(db, tc)
    await _target(db, client_factory)
    token = await _run_token(run)
    _err, own = _tool(tc, token, "ask_project", project_key="QBB", question="Ours?")
    _err, other = _tool(tc, _personal(tc), "ask_project", project_key="QBB", question="Not the task's?")
    err, out = _tool(tc, token, "get_question", question_id=own["question_id"])
    assert not err and out["ref"] == own["ref"]
    for name in ("get_question", "withdraw_question"):
        err, text_ = _tool(tc, token, name, question_id=other["question_id"])
        assert err and "question_not_found" in text_, (name, text_)
    err, out = _tool(tc, token, "withdraw_question", question_id=own["question_id"])
    assert not err and out == {"status": "withdrawn"}


async def test_routing_does_not_double_book_a_slot(client, db):
    m1, _m2, asker = await _world(client, db)
    agent = await _agent(client, m1, max_runs=1)
    q1 = await _ask_in_own_session(asker, body="First?")  # no runner yet: both stay queued
    q2 = await _ask_in_own_session(asker, body="Second?")
    _online(m1, agent)
    try:
        async with SessionLocal() as first, SessionLocal() as second:
            assert await routing.route_question(first, q1) is not None  # the slot, not yet committed
            racing = asyncio.create_task(routing.route_question(second, q2))
            await asyncio.sleep(0.3)
            await first.commit()
            assert await racing is None  # it waited for the first pass and saw the slot taken
            await second.commit()
    finally:
        _cleanup(m1)
    runs = (await db.execute(select(AgentRun).where(AgentRun.question_id.in_([q1, q2])))).scalars().all()
    assert [r.question_id for r in runs] == [q1]


@pytest.mark.parametrize("who", ["target_member", "asker"])
async def test_question_out_kb_document_readable_flag(client_factory, db, who):
    _asker, _member, _outsider, a, b, _c = await _ask_world(client_factory, db)
    q = (await _ask(a)).json()["question"]
    assert (await b.get(f"/api/questions/{q['id']}")).json()["kb_document_readable"] is False  # not filed yet
    r = await b.post(f"/api/questions/{q['id']}/answer", json={"answer_md": "HMAC over the body.", "citations": CITE})
    assert r.json()["kb_document_id"]
    client = b if who == "target_member" else a
    out = (await client.get(f"/api/questions/{q['id']}")).json()
    # the asker's project cannot read the target project's Knowledge Base; its members can
    assert out["kb_document_readable"] is (who == "target_member")
    assert out["kb_document_id"] == r.json()["kb_document_id"]
    assert uuid.UUID(out["kb_document_id"])
