import uuid

from sqlalchemy import select

from app.a2a.models import Question
from app.agent_runs.models import AgentRun
from app.audit.models import AuditLog
from app.auth.models import Role
from app.jobs.models import Job
from app.kb import access as kb_access
from app.memory import entities
from app.memory.models import MemConclusion, ScopeKind
from app.teams.models import TeamMember
from tests.factories import login, make_project, make_team, make_user


async def _world(client_factory, db):
    """QAA (asker's project, with task QAA-1) and QBB (the target). Clients: asker, target member, outsider."""
    asker = await make_user(db, name="Asker")
    target_member = await make_user(db, name="Target member")
    outsider = await make_user(db)
    a, b, c = client_factory(), client_factory(), client_factory()
    await make_project(a, db, "QAA", asker)
    await make_project(b, db, "QBB", target_member)
    await make_team(db, outsider)
    await login(a, asker)
    await a.post("/api/projects/QAA/tasks", json={"title": "Needs the QBB API", "type": "task"})
    await login(b, target_member)
    await login(c, outsider)
    return asker, target_member, outsider, a, b, c


async def _ask(client, **body):
    payload = {"project_key": "QBB", "body": "What payload does /orders/sync send?\nAnd how is it signed?", **body}
    return await client.post("/api/questions", json=payload)


async def test_ask_numbers_and_audits_and_queues_route(client_factory, db):
    _asker, *_rest, a, _b, _c = await _world(client_factory, db)
    r = await _ask(a, context="Tried reading the docs", task_key="QAA-1")
    assert r.status_code == 201, r.text
    q = r.json()["question"]
    assert (q["ref"], q["status"], q["title"]) == ("QBB-Q1", "queued", "What payload does /orders/sync send?")
    assert q["from_task"] == {"key": "QAA-1", "title": "Needs the QBB API"}
    assert q["asked_by"]["user"]["name"] == "Asker" and q["can_withdraw"] is True and q["can_answer"] is False
    second = (await _ask(a)).json()["question"]
    assert second["ref"] == "QBB-Q2"
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "a2a.question.asked"))).scalars().all()
    assert "a2a.route" in [j.kind for j in (await db.execute(select(Job))).scalars()]


async def test_title_defaults_to_first_line_and_limits(client_factory, db):
    *_users, a, _b, _c = await _world(client_factory, db)
    r = await _ask(a, body="x" * 4001)
    assert r.status_code == 422
    r = await _ask(a, context="y" * 8001)
    assert r.status_code == 422
    r = await _ask(a, body="Line\x00 one\nline two", title="")
    assert r.json()["question"]["title"] == "Line one" and r.json()["question"]["body"] == "Line one\nline two"
    r = await _ask(a, title="Explicit title")
    assert r.json()["question"]["title"] == "Explicit title"


async def test_viewer_cannot_ask_and_unknown_project_404(client_factory, db):
    *_users, a, _b, _c = await _world(client_factory, db)
    viewer = await make_user(db, role=Role.viewer)
    v = client_factory()
    await login(v, viewer)
    assert (await _ask(v)).status_code == 403
    r = await _ask(a, project_key="NOPE")
    assert r.status_code == 404 and r.json()["detail"] == "project_not_found"
    assert (await _ask(a, task_key="QBB-1")).status_code == 404  # not the asker's task


async def test_open_question_cap_429(client_factory, db):
    *_users, a, _b, _c = await _world(client_factory, db)
    for _ in range(20):
        assert (await _ask(a)).status_code == 201
    r = await _ask(a)
    assert r.status_code == 429 and r.json()["detail"] == "too_many_open_questions"


async def test_visibility_matrix(client_factory, db):
    _asker, _target_member, _outsider, a, b, c = await _world(client_factory, db)
    qa_member = await make_user(db)
    team_id = (await a.get("/api/projects/QAA")).json()["team_ids"][0]
    db.add(TeamMember(team_id=uuid.UUID(team_id), user_id=qa_member.id))
    await db.commit()
    m = client_factory()
    await login(m, qa_member)
    q = (await _ask(a, task_key="QAA-1")).json()["question"]
    plain = (await _ask(a)).json()["question"]
    for client, can in ((a, True), (b, True), (m, True), (c, False)):
        assert (await client.get(f"/api/questions/{q['id']}")).status_code == (200 if can else 404)
    assert (await m.get(f"/api/questions/{plain['id']}")).status_code == 404  # no task link: not QAA's business
    assert (await b.get(f"/api/questions/{plain['id']}")).json()["can_answer"] is True
    incoming = (await b.get("/api/questions", params={"box": "incoming"})).json()
    assert {x["id"] for x in incoming} == {q["id"], plain["id"]}
    assert (await c.get("/api/questions", params={"box": "incoming"})).json() == []
    assert {x["id"] for x in (await a.get("/api/questions", params={"box": "mine"})).json()} == {q["id"], plain["id"]}
    assert [x["id"] for x in (await a.get("/api/tasks/QAA-1/questions")).json()] == [q["id"]]


async def test_suggestions_only_what_asker_can_read(client_factory, db):
    _asker, _target_member, _outsider, a, b, _c = await _world(client_factory, db)
    await kb_access.ensure_spaces(db)
    org = await kb_access.org_space(db)
    await db.commit()
    qbb_space = (await b.get("/api/kb/spaces")).json()
    qbb = next(s for s in qbb_space if s["kind"] == "project")
    await b.post(f"/api/kb/spaces/{qbb['id']}/documents",
                 json={"title": "Orders sync payload", "body_md": "The orders sync webhook sends JSON."})
    await b.post(f"/api/kb/spaces/{org.id}/documents",
                 json={"title": "Webhook signing", "body_md": "All orders webhooks are signed with HMAC."})
    entity = await entities.org_entity(db)
    db.add(MemConclusion(entity_id=entity.id, text="Orders webhooks are signed with HMAC SHA256", kind="observed",
                         scope_kind=ScopeKind.org))
    await db.commit()
    r = await a.post("/api/questions/suggest", json={"project_key": "QBB", "body": "orders webhook signed payload"})
    titles = [s["title"] for s in r.json()]
    assert "Webhook signing" in titles and "Orders webhooks are signed with HMAC SHA256" in titles
    assert "Orders sync payload" not in titles  # the asker cannot read QBB's space
    member_titles = [s["title"] for s in (await b.post("/api/questions/suggest",
                     json={"project_key": "QBB", "body": "orders webhook signed payload"})).json()]
    assert "Orders sync payload" in member_titles
    asked = (await _ask(a, body="orders webhook signed payload")).json()
    assert [s["title"] for s in asked["suggestions"]] == titles


async def test_withdraw_by_asker_only_and_cancels_active_run(client_factory, db):
    asker, _target_member, _outsider, a, b, _c = await _world(client_factory, db)
    q = (await _ask(a)).json()["question"]
    agent = (await b.post("/api/agents", json={"program": "claude_code"})).json()
    run = AgentRun(question_id=uuid.UUID(q["id"]), agent_id=uuid.UUID(agent["id"]), requested_by=asker.id,
                   policy="read_only", prompt="p")
    db.add(run)
    await db.commit()
    assert (await b.post(f"/api/questions/{q['id']}/withdraw")).status_code == 403
    r = await a.post(f"/api/questions/{q['id']}/withdraw")
    assert r.status_code == 200 and r.json()["status"] == "withdrawn" and r.json()["can_withdraw"] is False
    await db.refresh(run)
    assert run.status == "cancelled"
    assert (await a.post(f"/api/questions/{q['id']}/withdraw")).status_code == 409


async def test_task_waiting_on_lists_targets_of_open_questions(client_factory, db):
    *_users, a, _b, _c = await _world(client_factory, db)
    q = (await _ask(a, task_key="QAA-1")).json()["question"]
    assert (await a.get("/api/tasks/QAA-1")).json()["waiting_on"] == ["QBB"]
    await a.post(f"/api/questions/{q['id']}/withdraw")
    assert (await a.get("/api/tasks/QAA-1")).json()["waiting_on"] == []
    assert (await db.execute(select(Question))).scalar_one().status == "withdrawn"
