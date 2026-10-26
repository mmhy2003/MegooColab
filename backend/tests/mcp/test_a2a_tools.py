"""Agent-to-agent MCP tools: asking from task runs and personal tokens, answering from answering runs."""

import uuid

from sqlalchemy import select, update

from app.a2a.models import Question
from app.agent_runs.models import AgentRun
from app.agents.models import Agent
from app.audit.models import AuditLog
from app.core.db import SessionLocal
from app.kb import access as kb_access
from tests.factories import login, make_project, make_user
from tests.mcp.test_workflow_tools import _personal, _run_token, _tool
from tests.workflow.test_engine import _started


async def _target(db, client_factory):
    """QBB, the target project, with a plain member; returns (member, member's client)."""
    member = await make_user(db, name="QBB member")
    await make_project(client_factory(), db, "QBB", member)
    mc = client_factory()
    await login(mc, member)
    return member, mc


async def _answer_run(db, owner, q_id, mode="manual"):
    agent = Agent(owner_id=owner.id, name=f"answerer-{uuid.uuid4().hex[:4]}", program="claude_code", answer_mode=mode)
    db.add(agent)
    await db.flush()
    run = AgentRun(question_id=q_id, agent_id=agent.id, requested_by=owner.id, policy="read_only", prompt="p")
    db.add(run)
    await db.execute(update(Question).where(Question.id == q_id).values(status="routed"))
    await db.commit()
    return run, agent


async def _ask(tc, token, **kw):
    return _tool(tc, token, "ask_project", project_key="QBB", question="How are retries signed?", **kw)


async def test_ask_project_from_task_run_links_task_and_refuses_other_task(db, tc_factory, client_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _target(db, client_factory)
    token = await _run_token(run)
    err, out = await _ask(tc, token)
    assert not err, out
    assert out["ref"] == "QBB-Q1" and out["status"] == "queued"
    q = (await db.execute(select(Question))).scalar_one()
    assert (q.from_task_id, str(q.asked_by_agent_id)) == (b.task_id, b.agent["id"])
    err, text = await _ask(tc, token, task_key="PAY-99")
    assert err and "wrong_task" in text


async def test_answer_run_tools_allowed_and_refused(db, tc_factory, client_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    member, _mc = await _target(db, client_factory)
    err, out = await _ask(tc, _personal(tc))
    run, _agent = await _answer_run(db, member, uuid.UUID(out["question_id"]))
    token = await _run_token(run)
    for name, args in (("get_question", {"question_id": out["question_id"]}), ("kb_search", {"query": "x"}),
                       ("search_memory", {"query": "retries signed"})):
        err, text = _tool(tc, token, name, **args)
        assert not err, (name, text)
    for name, args in (("get_task", {"key": b.key}), ("kb_write", {"title": "t", "body_md": "b"}),
                       ("ask_project", {"project_key": "PAY", "question": "q"}),
                       ("submit_design", {"key": b.key, "markdown": "# D"})):
        err, text = _tool(tc, token, name, **args)
        assert err and "not_allowed_in_role" in text, (name, text)


async def test_submit_answer_auto_mode_answers_and_scrubs(db, tc_factory, client_factory):
    tc = tc_factory(lifespan=True)
    await _started(db, tc)
    member, _mc = await _target(db, client_factory)
    _err, out = await _ask(tc, _personal(tc))
    run, agent = await _answer_run(db, member, uuid.UUID(out["question_id"]), mode="auto")
    token = await _run_token(run)
    err, res = _tool(tc, token, "submit_answer", answer_md="Signed with key AKIAABCDEFGHIJKLMNOP in app/sign.py",
                     citations=[{"path": "app/sign.py", "start_line": 3, "end_line": 9}])
    assert not err and res == {"status": "answered"}
    q = await db.get(Question, uuid.UUID(out["question_id"]), populate_existing=True)
    assert "[redacted]" in q.answer_md and "AKIA" not in q.answer_md and q.redacted is True
    assert (q.answer_source, q.answered_by_agent_id, q.citations[0]["path"]) == ("agent", agent.id, "app/sign.py")
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "a2a.answer.redacted"))).scalars().all()


async def test_submit_answer_manual_mode_creates_draft(db, tc_factory, client_factory):
    tc = tc_factory(lifespan=True)
    await _started(db, tc)
    member, _mc = await _target(db, client_factory)
    _err, out = await _ask(tc, _personal(tc))
    run, agent = await _answer_run(db, member, uuid.UUID(out["question_id"]))
    err, res = _tool(tc, await _run_token(run), "submit_answer", answer_md="See app/sign.py", citations=[])
    assert not err and res == {"status": "draft"}
    q = await db.get(Question, uuid.UUID(out["question_id"]), populate_existing=True)
    assert (q.draft_md, q.draft_agent_id, q.answer_md) == ("See app/sign.py", agent.id, None)


async def test_submit_answer_other_question_or_after_run_ended_refused(db, tc_factory, client_factory):
    tc = tc_factory(lifespan=True)
    await _started(db, tc)
    member, _mc = await _target(db, client_factory)
    personal = _personal(tc)
    _e, first = await _ask(tc, personal)
    _e, second = await _ask(tc, personal)
    run, _agent = await _answer_run(db, member, uuid.UUID(first["question_id"]))
    token = await _run_token(run)
    err, text = _tool(tc, token, "get_question", question_id=second["question_id"])
    assert err and "question_not_found" in text
    err, text = _tool(tc, personal, "submit_answer", answer_md="x", citations=[])
    assert err and "not_allowed_in_role" in text
    await db.execute(update(Question).where(Question.id == uuid.UUID(first["question_id"])).values(status="answered"))
    await db.commit()
    err, text = _tool(tc, token, "submit_answer", answer_md="x", citations=[])
    assert err and "question_not_routed" in text
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run.id).values(status="completed"))
        await s.commit()
    err, text = _tool(tc, token, "submit_answer", answer_md="x", citations=[])
    assert err  # the token died with the run


async def test_find_answer_returns_only_readable_suggestions(db, tc_factory, client_factory):
    tc = tc_factory(lifespan=True)
    await _started(db, tc)
    _member, mc = await _target(db, client_factory)
    await kb_access.ensure_spaces(db)
    org = await kb_access.org_space(db)
    await db.commit()
    qbb = next(s for s in (await mc.get("/api/kb/spaces")).json() if s["kind"] == "project")
    await mc.post(f"/api/kb/spaces/{qbb['id']}/documents",
                  json={"title": "Retries signing internals", "body_md": "retries signed"})
    await mc.post(f"/api/kb/spaces/{org.id}/documents",
                  json={"title": "Retries signed everywhere", "body_md": "retries signed"})
    err, out = _tool(tc, _personal(tc), "find_answer", project_key="QBB", question="retries signed")
    titles = [s["title"] for s in out["suggestions"]]
    assert not err and "Retries signed everywhere" in titles and "Retries signing internals" not in titles


async def test_tool_list_includes_a2a_tools():
    from app.mcp_server.server import build_mcp

    mcp, _ = build_mcp()
    names = {t.name for t in await mcp.list_tools()}
    assert {"find_answer", "ask_project", "get_question", "withdraw_question", "submit_answer"} <= names
