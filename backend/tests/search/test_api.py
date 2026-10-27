"""The search API (Plan 9 Task 4): typo-tolerant, grouped, filtered, and never showing what a person can't open."""

import uuid

from sqlalchemy import delete, select

from app.a2a.models import Question
from app.agents.models import Agent, AgentBinding, AgentProgram
from app.audit.models import AuditLog
from app.auth.models import Role
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.jobs.models import Job
from app.kb import access as kb_access
from app.projects.models import BoardColumn
from app.tasks.models import Task
from app.teams.models import TeamMember
from tests.factories import login, make_project, make_team, make_user
from tests.search.conftest import drain

PRE, POST = "", ""


async def _project(client, db, key, *members):
    project, manager, team = await make_project(client, db, key, *members)
    return uuid.UUID(project["id"]), manager, team


async def _task(db, project_id, number, title, category="before", **kw):
    col = (await db.execute(select(BoardColumn).where(BoardColumn.project_id == project_id,
                                                      BoardColumn.category == category).limit(1))).scalar_one()
    task = Task(project_id=project_id, number=number, type=kw.pop("type", "task"), title=title, column_id=col.id,
                position=float(number), **kw)
    db.add(task)
    await db.commit()
    return task


async def _quick(client, q):
    r = await client.get("/api/search/quick", params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()


async def _full(client, **params):
    r = await client.get("/api/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _plain(text: str) -> str:
    return text.replace(PRE, "").replace(POST, "")


async def test_quick_groups_by_kind_with_typos_and_prefix(client, db, meili_index):
    pid, _, _ = await _project(client, db, "PAY")
    await _task(db, pid, 1, "Retry failed card payments")
    for n in range(2, 9):
        await _task(db, pid, n, f"Payment report {n}")
    space = await kb_access.space_for_project(db, pid)
    r = await client.post(f"/api/kb/spaces/{space.id}/documents",
                          json={"title": "Payment retry policy", "body_md": "Every payment is retried."})
    assert r.status_code == 201
    await drain()
    out = await _quick(client, "retyr payments")
    assert next(g["kind"] for g in out["groups"]) == "task"
    titles = [_plain(h["title"]) for g in out["groups"] for h in g["hits"]]
    assert "Retry failed card payments" in titles
    assert any(PRE in h["title"] for g in out["groups"] for h in g["hits"])
    out = await _quick(client, "paym")
    kinds = [g["kind"] for g in out["groups"]]
    assert kinds == [k for k in ("task", "document", "project", "team", "person", "agent", "question") if k in kinds]
    tasks = next(g for g in out["groups"] if g["kind"] == "task")
    assert len(tasks["hits"]) == 5 and out["total"] >= 9
    hit = tasks["hits"][0]
    assert hit["url"].startswith("/projects/PAY/tasks/") and hit["key"].startswith("PAY-")


async def test_keys_match_exactly(client, db, meili_index):
    pid, _, _ = await _project(client, db, "PAY")
    await _task(db, pid, 24, "Twenty four")
    await _task(db, pid, 42, "Forty two")
    await drain()
    out = await _quick(client, "PAY-42")
    tasks = next(g for g in out["groups"] if g["kind"] == "task")
    assert [_plain(h["key"]) for h in tasks["hits"]] == ["PAY-42"]


async def _two_projects(client, db):
    ann = await make_user(db, name="Ann Secret")
    bob = await make_user(db, name="Bob Public")
    sec, _, _ = await _project(client, db, "SEC", ann)
    pay, _, pay_team = await _project(client, db, "PAY", bob)
    await _task(db, sec, 1, "Secret rollout plan", category="done", assignee_user_id=ann.id)
    await _task(db, pay, 1, "Public rollout notes", assignee_user_id=bob.id)
    agent = Agent(owner_id=ann.id, name="Rollout agent", program=AgentProgram.codex)
    db.add(agent)
    await db.flush()
    db.add_all([AgentBinding(agent_id=agent.id, project_id=sec, local_path="/a"),
                AgentBinding(agent_id=agent.id, project_id=pay, local_path="/b")])
    await db.commit()
    await drain()
    return ann, bob, sec, pay, pay_team


async def test_counts_and_facets_never_include_unreadable_items(client, db, meili_index):
    _, bob, _, pay, _ = await _two_projects(client, db)
    await login(client, bob)
    out = await _full(client, q="rollout")
    assert all("SEC" not in (h["key"] or "") and "Secret" not in h["title"] for h in out["hits"])
    assert out["total"] == len(out["hits"]) == 2  # Bob's task and the agent
    facets = out["facets"]
    assert facets["kind"] == {"task": 1, "agent": 1}
    assert [p["key"] for p in facets["project"]] == ["PAY"]
    assert [a["name"] for a in facets["assignee"]] == ["Bob Public"]
    assert facets["status"] == {"before": 1}
    agent = next(h for h in out["hits"] if h["kind"] == "agent")
    assert agent["card"]["projects"] == [{"id": str(pay), "key": "PAY"}]
    quick = await _quick(client, "rollout")
    assert quick["total"] == 2
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    out = await _full(client, q="rollout")
    assert out["facets"]["kind"] == {"task": 2, "agent": 1}
    agent = next(h for h in out["hits"] if h["kind"] == "agent")
    assert {p["key"] for p in agent["card"]["projects"]} == {"PAY", "SEC"}


async def test_revoked_membership_takes_effect_on_the_next_search(client, db, meili_index):
    _, bob, _, _, pay_team = await _two_projects(client, db)
    await login(client, bob)
    assert (await _full(client, q="rollout", kind="task"))["total"] == 1
    await db.execute(delete(TeamMember).where(TeamMember.team_id == pay_team.id, TeamMember.user_id == bob.id))
    await db.commit()
    assert (await _full(client, q="rollout", kind="task"))["total"] == 0  # no drain: permissions are read now


async def test_questions_follow_their_read_rule(client, db, meili_index):
    asker = await make_user(db)
    target_member = await make_user(db)
    source_member = await make_user(db)
    outsider = await make_user(db)
    target, _, _ = await _project(client, db, "QBB", target_member)
    source, _, _ = await _project(client, db, "QAA", source_member)
    task = await _task(db, source, 1, "Needs refunds")
    db.add(Question(target_project_id=target, number=1, from_task_id=task.id, asked_by_user_id=asker.id,
                    title="How do refunds work?", body="Details", status="queued"))
    await db.commit()
    await drain()
    for user, visible in ((asker, True), (target_member, True), (source_member, True), (outsider, False)):
        await login(client, user)
        out = await _full(client, q="refunds", kind="question")
        assert (out["total"] == 1) is visible, user.name


async def test_filters_sort_and_paging(client, db, meili_index):
    pid, manager, _ = await _project(client, db, "PAY")
    for n in range(1, 26):
        await _task(db, pid, n, f"Invoice item {n}", category="done" if n % 2 else "before",
                    type="bug" if n % 5 == 0 else "task", assignee_user_id=manager.id if n == 10 else None)
    await drain()
    page1 = await _full(client, q="invoice", kind="task")
    page2 = await _full(client, q="invoice", kind="task", offset=20)
    assert page1["total"] == 25 and len(page1["hits"]) == 20 and len(page2["hits"]) == 5
    assert (await _full(client, q="invoice", status="done"))["total"] == 13
    assert (await _full(client, q="invoice", type="bug"))["total"] == 5
    out = await _full(client, q="invoice", assignee=f"user:{manager.id}")
    assert [_plain(h["key"]) for h in out["hits"]] == ["PAY-10"]
    newest = await _full(client, q="invoice", kind="task", sort="newest")
    stamps = [h["updated_at"] for h in newest["hits"]]
    assert stamps == sorted(stamps, reverse=True)
    assert (await _full(client, q="invoice", updated="7d"))["total"] == 25


async def test_filter_values_cannot_widen_the_query(client, db, meili_index):
    _, bob, _, _, _ = await _two_projects(client, db)
    await login(client, bob)
    out = await _full(client, q="rollout", label='x" OR readers = "all')
    assert out["total"] == 0
    out = await _full(client, q="rollout", label='bug\\" OR kind = "task')
    assert out["total"] == 0
    for params in ({"project": "not-a-uuid"}, {"kind": "secret"}, {"updated": "1d"}, {"status": "open"},
                   {"assignee": "team:" + str(uuid.uuid4())}, {"type": "spike"}):
        r = await client.get("/api/search", params={"q": "rollout", **params})
        assert (r.status_code, r.json()["detail"]) == (422, "invalid_filter"), params
    assert (await client.get("/api/search", params={"q": "x" * 201})).status_code == 422
    assert (await client.get("/api/search/quick", params={"q": ""})).status_code == 422


async def test_meaning_block(client, db, meili_index, monkeypatch):
    """Documents the Knowledge Base finds by meaning, not already among the word matches, form their own block."""
    from app.search import service as search_service

    pid, _, _ = await _project(client, db, "PAY")
    space = await kb_access.space_for_project(db, pid)
    billing = (await client.post(f"/api/kb/spaces/{space.id}/documents",
                                 json={"title": "Billing guide", "body_md": "Billing runs monthly."})).json()
    invoicing = (await client.post(f"/api/kb/spaces/{space.id}/documents",
                                   json={"title": "Invoicing", "body_md": "How we charge our customers."})).json()
    await drain()
    asked = []

    async def by_meaning(db_, user, q, **kw):
        asked.append((q, kw))
        return {"semantic": True, "results": [
            {"document_id": uuid.UUID(billing["id"]), "title": "Billing guide", "snippet": "Billing runs monthly."},
            {"document_id": uuid.UUID(invoicing["id"]), "title": "Invoicing", "snippet": "How we charge"},
        ]}

    monkeypatch.setattr(search_service.kb_search, "search", by_meaning)
    out = await _full(client, q="billing", meaning="true")
    assert out["meaning_available"] is True
    assert [_plain(h["title"]) for h in out["hits"]] == ["Billing guide"]  # the word match
    assert [h["title"] for h in out["meaning"]] == ["Invoicing"]  # only what the words missed
    assert out["meaning"][0]["url"] == f"/kb/doc/{invoicing['id']}"
    assert asked == [("billing", {"limit": 5})]
    assert (await _full(client, q="billing"))["meaning"] is None
    assert (await _full(client, q="billing", meaning="true", kind="task"))["meaning"] is None
    monkeypatch.setattr(get_settings(), "ai_fake", False)
    out = await _full(client, q="billing", meaning="true")
    assert (out["meaning"], out["meaning_available"]) == (None, False)


async def test_search_unavailable_is_503(client, db, meili_index):
    await _project(client, db, "PAY")
    settings = get_settings()
    good = settings.meili_url
    settings.meili_url = "http://127.0.0.1:9"
    try:
        for url in ("/api/search/quick", "/api/search"):
            r = await client.get(url, params={"q": "anything"})
            assert (r.status_code, r.json()["detail"]) == (503, "search_unavailable"), url
    finally:
        settings.meili_url = good


async def test_admin_search_status_and_rebuild(client, db, meili_index):
    await _project(client, db, "PAY")
    member = await make_user(db)
    await make_team(db, member)
    await login(client, member)
    assert (await client.get("/api/admin/search")).status_code == 403
    assert (await client.post("/api/admin/search/rebuild")).status_code == 403
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    r = await client.post("/api/admin/search/rebuild")
    assert r.status_code == 202, r.text
    async with SessionLocal() as s:
        assert await s.scalar(select(Job.id).where(Job.kind == "search.rebuild")) is not None
        assert await s.scalar(select(AuditLog.id).where(AuditLog.action == "search.rebuild")) is not None
    await drain()
    out = (await client.get("/api/admin/search")).json()
    assert out["available"] is True and out["documents"] > 0

