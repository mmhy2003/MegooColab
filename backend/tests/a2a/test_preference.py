"""Choosing who answers a question: any free agent (as before), a program, or one agent; and whether the question
waits for them or lets another agent answer when they're busy or offline."""

import uuid

from sqlalchemy import update

from app.a2a import routing, service
from app.a2a.models import Question, QuestionStatus
from app.core.db import SessionLocal
from tests.a2a.test_routing import _agent, _cleanup, _online, _runs, _world
from tests.factories import login


async def _codex(client, user):
    await login(client, user)
    r = await client.post("/api/agents", json={"program": "codex", "name": f"codex-{uuid.uuid4().hex[:6]}"})
    agent = r.json()
    r = await client.put(f"/api/agents/{agent['id']}/bindings",
                         json={"bindings": [{"project_ref": "QBB", "local_path": "/repo/qbb"}]})
    assert r.status_code == 200, r.text
    return agent


async def _ask(client, asker, **prefer):
    await login(client, asker)
    r = await client.post("/api/questions", json={"project_key": "QBB", "body": "How is sync signed?", **prefer})
    assert r.status_code == 201, r.text
    return r.json()["question"]


async def test_a_program_is_preferred_over_a_less_busy_agent(client, db, monkeypatch):
    monkeypatch.setattr("app.a2a.service.suggest", _no_suggestions)
    m1, m2, asker = await _world(client, db)
    codex = await _codex(client, m1)
    claude = await _agent(client, m2, max_runs=3)
    await _online(m1, codex)
    await _online(m2, claude)
    try:
        q = await _ask(client, asker, prefer_program="claude_code")
        [run] = await _runs(db, uuid.UUID(q["id"]))
        assert str(run.agent_id) == claude["id"]
        assert q["preference"] == {"program": "claude_code", "agent": None, "if_busy": "wait"}
    finally:
        _cleanup(m1, m2)


async def test_one_agent_can_be_chosen(client, db, monkeypatch):
    monkeypatch.setattr("app.a2a.service.suggest", _no_suggestions)
    m1, m2, asker = await _world(client, db)
    codex = await _codex(client, m1)
    claude = await _agent(client, m2)
    await _online(m1, codex)
    await _online(m2, claude)
    try:
        q = await _ask(client, asker, prefer_agent_id=codex["id"], if_busy="another")
        [run] = await _runs(db, uuid.UUID(q["id"]))
        assert str(run.agent_id) == codex["id"]
        assert q["preference"]["agent"] == {"id": codex["id"], "name": codex["name"]}
        assert q["preference"]["if_busy"] == "another"
    finally:
        _cleanup(m1, m2)


async def test_waiting_for_them_keeps_it_queued_until_one_is_free(client, db, monkeypatch):
    monkeypatch.setattr("app.a2a.service.suggest", _no_suggestions)
    m1, m2, asker = await _world(client, db)
    codex = await _codex(client, m1)
    claude = await _agent(client, m2)
    await _online(m1, codex)  # the Claude Code agent is offline
    try:
        q = await _ask(client, asker, prefer_program="claude_code", if_busy="wait")
        qid = uuid.UUID(q["id"])
        assert await _runs(db, qid) == []
        assert (await db.get(Question, qid)).status == QuestionStatus.queued
        await _online(m2, claude)
        async with SessionLocal() as s:
            run = await routing.route_question(s, qid)
            await s.commit()
        assert str(run.agent_id) == claude["id"]
    finally:
        _cleanup(m1, m2)


async def test_letting_another_answer_goes_to_a_free_agent(client, db, monkeypatch):
    monkeypatch.setattr("app.a2a.service.suggest", _no_suggestions)
    m1, m2, asker = await _world(client, db)
    codex = await _codex(client, m1)
    await _agent(client, m2)  # Claude Code, offline
    await _online(m1, codex)
    try:
        q = await _ask(client, asker, prefer_program="claude_code", if_busy="another")
        [run] = await _runs(db, uuid.UUID(q["id"]))
        assert str(run.agent_id) == codex["id"]
    finally:
        _cleanup(m1)


async def test_waiting_goes_to_a_person_once_every_chosen_agent_has_tried(client, db, monkeypatch):
    monkeypatch.setattr("app.a2a.service.suggest", _no_suggestions)
    m1, m2, asker = await _world(client, db)
    codex = await _codex(client, m1)
    claude = await _agent(client, m2)
    await _online(m1, codex)
    try:
        q = await _ask(client, asker, prefer_agent_id=claude["id"], if_busy="wait")
        qid = uuid.UUID(q["id"])
        await db.execute(update(Question).where(Question.id == qid).values(tried_agent_ids=[claude["id"]]))
        await db.commit()
        async with SessionLocal() as s:
            assert await routing.route_question(s, qid) is None
            await s.commit()
        # the Codex agent never tried, but it wasn't chosen: a person answers
        assert (await db.get(Question, qid, populate_existing=True)).status == QuestionStatus.needs_human
    finally:
        _cleanup(m1)


async def test_a_choice_must_be_one_of_the_projects_agents(client, db, monkeypatch):
    monkeypatch.setattr("app.a2a.service.suggest", _no_suggestions)
    m1, m2, asker = await _world(client, db)
    unbound = await _agent(client, m1, bind=False)
    claude = await _agent(client, m2)
    await login(client, asker)
    for body, detail in [
        ({"prefer_agent_id": unbound["id"]}, "agent_not_available"),
        ({"prefer_agent_id": claude["id"], "prefer_program": "codex"}, "invalid_preference"),
    ]:
        r = await client.post("/api/questions", json={"project_key": "QBB", "body": "B?", **body})
        assert r.status_code == 422 and r.json()["detail"] == detail, r.text


async def test_any_free_agent_is_as_before(client, db, monkeypatch):
    monkeypatch.setattr("app.a2a.service.suggest", _no_suggestions)
    _m1, _m2, asker = await _world(client, db)
    q = await _ask(client, asker)
    assert q["preference"] is None


async def test_the_asker_sees_the_projects_agents_and_whether_each_is_free(client, db):
    m1, m2, asker = await _world(client, db)
    codex = await _codex(client, m1)
    claude = await _agent(client, m2)
    await _online(m1, codex)
    try:
        await login(client, asker)  # not a member of QBB
        r = await client.get("/api/questions/targets/QBB/agents")
        assert r.status_code == 200, r.text
        rows = {a["id"]: a for a in r.json()}
        assert rows[codex["id"]] == {"id": codex["id"], "name": codex["name"], "program": "codex", "state": "free"}
        assert rows[claude["id"]]["state"] == "offline"
        assert (await client.get("/api/questions/targets/NOPE/agents")).status_code == 404
    finally:
        _cleanup(m1)


async def _no_suggestions(*_args, **_kwargs):
    return []
