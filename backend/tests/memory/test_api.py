import uuid

from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import Role
from app.memory import entities
from app.memory.models import (
    ConclusionStatus,
    EntityKind,
    MemCard,
    MemConclusion,
    MemPremise,
    MemSuppression,
    ScopeKind,
)
from app.tasks.models import Comment, Task
from tests.factories import login, make_project, make_team, make_user
from tests.memory.test_search import _add


async def _world(client, db):
    member = await make_user(db, name="Mia")
    viewer = await make_user(db, role=Role.viewer)
    outsider = await make_user(db)
    admin = await make_user(db, role=Role.admin)
    project, manager, team = await make_project(client, db, "PAY", member, viewer)
    await make_team(db, outsider)
    await entities.ensure_core_entities(db)
    await db.commit()
    return {"member": member, "viewer": viewer, "outsider": outsider, "admin": admin, "manager": manager,
                "pid": uuid.UUID(project["id"]), "team": team}


async def _person_fact(db, person, text, scope):
    entity = await entities.ensure_entity(db, EntityKind.user, person.id)
    kind, ref = scope
    row = MemConclusion(entity_id=entity.id, text=text, kind="observed", scope_kind=kind,
                        scope_team_id=ref if kind == ScopeKind.team else None,
                        scope_project_id=ref if kind == ScopeKind.project else None)
    db.add(row)
    await db.commit()
    return entity, row


async def test_entity_list_counts_only_readable(client, db):
    w = await _world(client, db)
    entity, _ = await _person_fact(db, w["member"], "Mia owns billing", (ScopeKind.project, w["pid"]))
    await _person_fact(db, w["member"], "Mia likes tea", (ScopeKind.org, None))
    await login(client, w["member"])
    mine = {e["id"]: e for e in (await client.get("/api/memory/entities", params={"kind": "user"})).json()}
    assert mine[str(entity.id)]["conclusion_count"] == 2
    await login(client, w["outsider"])
    seen = (await client.get("/api/memory/entities")).json()
    person = next(e for e in seen if e["id"] == str(entity.id))
    assert person["conclusion_count"] == 1
    assert not any(e["kind"] == "project" for e in seen)
    assert {e["kind"] for e in seen} >= {"org", "team", "user"}
    filtered = (await client.get("/api/memory/entities", params={"q": "mi"})).json()
    assert [e["name"] for e in filtered] == ["Mia"]


async def test_entity_detail_hides_unreadable_cards_and_404s_unreadable_project_entity(client, db):
    w = await _world(client, db)
    person = await entities.ensure_entity(db, EntityKind.user, w["member"].id)
    project_entity = await entities.ensure_entity(db, EntityKind.project, w["pid"])
    db.add_all([
        MemCard(entity_id=person.id, scope_kind=ScopeKind.project, scope_project_id=w["pid"], summary_md="In PAY"),
        MemCard(entity_id=person.id, scope_kind=ScopeKind.org, summary_md="Everywhere"),
    ])
    await db.commit()
    await login(client, w["outsider"])
    detail = (await client.get(f"/api/memory/entities/{person.id}")).json()
    assert [c["summary_md"] for c in detail["cards"]] == ["Everywhere"]
    assert (await client.get(f"/api/memory/entities/{project_entity.id}")).status_code == 404
    await login(client, w["member"])
    detail = (await client.get(f"/api/memory/entities/{person.id}")).json()
    assert sorted(c["summary_md"] for c in detail["cards"]) == ["Everywhere", "In PAY"]


async def test_conclusions_paging_and_status_filter(client, db):
    w = await _world(client, db)
    org = await entities.org_entity(db)
    for i in range(5):
        await _add(db, f"Fact number {i}")
    await _add(db, "Gone fact", status=ConclusionStatus.deleted)
    await login(client, w["member"])
    page = (await client.get(f"/api/memory/entities/{org.id}/conclusions", params={"limit": 3})).json()
    assert len(page["items"]) == 3 and page["next_cursor"]
    rest = (await client.get(f"/api/memory/entities/{org.id}/conclusions",
                             params={"limit": 3, "cursor": page["next_cursor"]})).json()
    assert len(rest["items"]) == 2 and rest["next_cursor"] is None
    assert {i["text"] for i in page["items"] + rest["items"]} == {f"Fact number {i}" for i in range(5)}
    deleted = (await client.get(f"/api/memory/entities/{org.id}/conclusions", params={"status": "deleted"})).json()
    assert [i["text"] for i in deleted["items"]] == ["Gone fact"]
    item = page["items"][0]
    assert item["scope"] == {"kind": "org", "id": None, "name": "Organization"} and item["can_edit"] is False


async def _task_fact(client, db, w, text="Payments retry webhooks"):
    task = (await db.execute(select(Task))).scalars().first()
    if task is None:
        await login(client, w["manager"])
        await client.post("/api/projects/PAY/tasks", json={"title": "Go", "type": "task"})
        task = (await db.execute(select(Task))).scalars().first()
    c = Comment(task_id=task.id, author_user_id=w["member"].id, body_md=text)
    db.add(c)
    await db.commit()
    row = await _add(db, text, scope=(ScopeKind.project, w["pid"]))
    row.source_kind, row.source_id, row.source_label = "comment", c.id, "Comment on PAY-1"
    await db.commit()
    return row


async def test_correct_creates_correction_supersedes_and_suppresses(client, db):
    w = await _world(client, db)
    row = await _task_fact(client, db, w)
    await login(client, w["member"])
    r = await client.post(f"/api/memory/conclusions/{row.id}/correct", json={"text": "Payments retry webhooks 5 times"})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["kind"] == "correction" and new["text"] == "Payments retry webhooks 5 times"
    assert new["source"] == {"kind": "comment", "label": "Comment on PAY-1", "link": "/projects/PAY/tasks/1"}
    await db.refresh(row)
    assert row.status == ConclusionStatus.superseded and str(row.superseded_by_id) == new["id"]
    [s] = (await db.execute(select(MemSuppression))).scalars().all()
    assert (s.source_id, s.text) == (row.source_id, "Payments retry webhooks")
    premise = (await db.execute(select(MemPremise))).scalar_one()
    assert (str(premise.conclusion_id), premise.premise_id) == (new["id"], row.id)
    assert (await client.post(f"/api/memory/conclusions/{row.id}/correct", json={"text": "x"})).status_code == 409


async def test_delete_soft_audited_and_suppressed(client, db):
    w = await _world(client, db)
    row = await _task_fact(client, db, w)
    await login(client, w["member"])
    assert (await client.delete(f"/api/memory/conclusions/{row.id}")).status_code == 204
    await db.refresh(row)
    assert row.status == ConclusionStatus.deleted
    assert (await db.execute(select(MemSuppression))).scalar_one().embedding_model == "fake/embed-64"
    log = (await db.execute(select(AuditLog).where(AuditLog.action == "memory.conclusion.deleted"))).scalar_one()
    assert log.target_id == row.id
    assert (await client.delete(f"/api/memory/conclusions/{row.id}")).status_code == 204  # idempotent
    assert len((await db.execute(select(MemSuppression))).scalars().all()) == 1


async def test_permissions_matrix_edit_403_vs_404(client, db):
    w = await _world(client, db)
    project_row = await _task_fact(client, db, w)
    org_row = await _add(db, "Org wide fact")
    await login(client, w["viewer"])
    assert (await client.post(f"/api/memory/conclusions/{project_row.id}/pin", json={"pinned": True})).status_code == 403
    await login(client, w["outsider"])
    assert (await client.post(f"/api/memory/conclusions/{project_row.id}/pin", json={"pinned": True})).status_code == 404
    assert (await client.get(f"/api/memory/conclusions/{project_row.id}")).status_code == 404
    await login(client, w["member"])
    assert (await client.post(f"/api/memory/conclusions/{org_row.id}/pin", json={"pinned": True})).status_code == 403
    r = await client.post(f"/api/memory/conclusions/{project_row.id}/pin", json={"pinned": True})
    assert r.status_code == 200 and r.json()["pinned"] is True
    await login(client, w["manager"])
    assert (await client.post(f"/api/memory/conclusions/{org_row.id}/pin", json={"pinned": True})).status_code == 200


async def test_reasoning_chain_depth_and_derived(client, db):
    w = await _world(client, db)
    rows = [await _add(db, f"Step {i} fact") for i in range(7)]
    for parent, child in zip(rows[1:], rows[:-1], strict=True):
        db.add(MemPremise(conclusion_id=parent.id, premise_id=child.id))
    await db.commit()
    await login(client, w["member"])
    detail = (await client.get(f"/api/memory/conclusions/{rows[6].id}")).json()
    depth, node = 0, detail["premises"]
    while node:
        depth += 1
        node = node[0]["premises"]
    assert depth == 5
    mid = (await client.get(f"/api/memory/conclusions/{rows[3].id}")).json()
    assert [d["text"] for d in mid["derived"]] == ["Step 4 fact"]


async def test_ask_endpoint_and_limits(client, db):
    w = await _world(client, db)
    await _add(db, "Webhooks are signed with HMAC")
    await login(client, w["member"])
    r = await client.post("/api/memory/ask", json={"question": "How are webhooks signed?", "project_key": "PAY"})
    assert r.status_code == 200 and r.json()["cited"][0]["text"] == "Webhooks are signed with HMAC"
    assert (await client.post("/api/memory/ask", json={"question": ""})).status_code == 422
    assert (await client.post("/api/memory/ask", json={"question": "x" * 1001})).status_code == 422
    await login(client, w["outsider"])
    r = await client.post("/api/memory/ask", json={"question": "webhooks?", "project_key": "PAY"})
    assert r.status_code == 404


async def test_dream_endpoints_admin_only(client, db):
    w = await _world(client, db)
    await login(client, w["manager"])
    assert (await client.post("/api/admin/memory/dream")).status_code == 403
    assert (await client.get("/api/admin/memory/dreams")).status_code == 403
    await login(client, w["admin"])
    r = await client.post("/api/admin/memory/dream")
    assert r.status_code == 201 and r.json()["status"] == "running"
    assert (await client.post("/api/admin/memory/dream")).json()["detail"] == "dream_running"
    assert [d["id"] for d in (await client.get("/api/admin/memory/dreams")).json()] == [r.json()["id"]]


async def test_products_crud(client, db):
    w = await _world(client, db)
    await login(client, w["member"])
    assert (await client.post("/api/memory/products", json={"name": "Atlas"})).status_code == 403
    await login(client, w["manager"])
    r = await client.post("/api/memory/products", json={"name": "Atlas", "description": "Billing",
                                                         "project_ids": [str(w["pid"])]})
    assert r.status_code == 201
    pid = r.json()["id"]
    detail = (await client.get(f"/api/memory/entities/{pid}")).json()
    assert detail["project_ids"] == [str(w["pid"])]
    r = await client.patch(f"/api/memory/products/{pid}", json={"name": "Atlas 2"})
    assert r.json()["name"] == "Atlas 2"
    assert (await client.delete(f"/api/memory/products/{pid}")).status_code == 204
    assert (await client.get(f"/api/memory/entities/{pid}")).status_code == 404
