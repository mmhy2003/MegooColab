import asyncio
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.models import Role
from app.core.events import Event
from app.jobs.models import Job
from app.kb import access
from app.kb.models import KbLink, KbRevision
from app.kb.service import diff, parse_links
from app.realtime.router import _visible
from tests.factories import DEFAULT_PASSWORD, login, make_project, make_team, make_user


async def _world(client, db):
    member = await make_user(db, name="Mia Member")
    viewer = await make_user(db, role=Role.viewer)
    outsider = await make_user(db)
    project, manager, team = await make_project(client, db, "PAY", member, viewer)
    other_team = await make_team(db, outsider)
    await access.ensure_spaces(db)
    await db.commit()
    org = await access.org_space(db)
    team_space = await access.space_for_team(db, team.id)
    other_space = await access.space_for_team(db, other_team.id)
    project_space = await access.space_for_project(db, project["id"])
    await db.commit()
    return {
        "member": member, "viewer": viewer, "outsider": outsider, "manager": manager, "project": project,
        "org": org, "team": team_space, "other": other_space, "pspace": project_space, "team_obj": team,
    }


async def _as(client, user):
    await login(client, user)
    return client


async def _create(client, space_id, title="Guide", body="hello", folder_id=None, status=201):
    r = await client.post(
        f"/api/kb/spaces/{space_id}/documents", json={"title": title, "body_md": body, "folder_id": folder_id}
    )
    assert r.status_code == status, r.text
    return r.json()


def test_parse_links():
    d = uuid.uuid4()
    tasks, docs = parse_links(
        f"see [[PAY-12]] and [[doc:{d}|Setup]] and [[doc:{d}]] [[pay-1]] [[doc:nope]] [[PAY-]] [[ PAY-3 ]]"
    )
    assert tasks == {"PAY-12"} and docs == {d}


async def test_create_update_creates_revisions_with_author(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    doc = await _create(client, w["team"].id, body="v1")
    assert doc["latest_revision"] == 1 and doc["can_write"] and doc["can_delete"]
    assert doc["path"] == "" and doc["space"]["kind"] == "team"
    r = await client.put(f"/api/kb/documents/{doc['id']}", json={"base_revision": 1, "body_md": "v2", "summary": "edit"})
    assert r.status_code == 200 and r.json()["latest_revision"] == 2
    assert r.json()["updated_by"]["user"]["name"] == "Mia Member"
    revs = (await client.get(f"/api/kb/documents/{doc['id']}/revisions")).json()
    assert [(x["revision"], x["summary"], x["author"]["user"]["id"]) for x in revs] == [
        (2, "edit", str(w["member"].id)),
        (1, None, str(w["member"].id)),
    ]
    assert revs[0]["author"]["agent"] is None
    r1 = (await client.get(f"/api/kb/documents/{doc['id']}/revisions/1")).json()
    assert r1["body_md"] == "v1"
    assert (await client.get(f"/api/kb/documents/{doc['id']}/revisions/9")).status_code == 404
    # an unchanged save adds no revision
    r = await client.put(f"/api/kb/documents/{doc['id']}", json={"base_revision": 2, "body_md": "v2"})
    assert r.status_code == 200 and r.json()["latest_revision"] == 2
    # saving queues (deduplicated) indexing
    jobs = (await db.execute(select(Job).where(Job.kind == "kb.embed"))).scalars().all()
    assert [j.dedupe_key for j in jobs] == [f"kb.embed:{doc['id']}"]


async def test_conflicting_update_409_no_lost_revision(client_factory, db):
    a, b = client_factory(), client_factory()
    w = await _world(a, db)
    await login(a, w["member"])
    await login(b, w["manager"])
    doc = await _create(a, w["team"].id, body="base")

    ra, rb = await asyncio.gather(
        a.put(f"/api/kb/documents/{doc['id']}", json={"base_revision": 1, "body_md": "from a"}),
        b.put(f"/api/kb/documents/{doc['id']}", json={"base_revision": 1, "body_md": "from b"}),
    )
    assert sorted([ra.status_code, rb.status_code]) == [200, 409]
    loser = ra if ra.status_code == 409 else rb
    assert loser.json()["detail"] == "kb_conflict"
    count = (await db.execute(select(func.count()).select_from(KbRevision))).scalar_one()
    assert count == 2


async def test_title_unique_in_folder_409(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    await _create(client, w["team"].id, title="Same")
    r = await client.post(f"/api/kb/spaces/{w['team'].id}/documents", json={"title": "Same", "body_md": ""})
    assert r.status_code == 409 and r.json()["detail"] == "title_taken"
    f = (await client.post(f"/api/kb/spaces/{w['team'].id}/folders", json={"name": "Sub"})).json()
    await _create(client, w["team"].id, title="Same", folder_id=f["id"])  # other folder: fine


async def test_limits_and_nul(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    r = await client.post(f"/api/kb/spaces/{w['org'].id}/documents", json={"title": "Big", "body_md": "x" * 500_001})
    assert r.status_code == 422 and r.json()["detail"] == "too_large"
    big = " ".join(f"w{i}é漢" for i in range(80_000))[:500_000]
    doc = await _create(client, w["org"].id, title="Max", body=big)
    assert doc["latest_revision"] == 1
    doc = await _create(client, w["org"].id, title="Nul\x00led", body="a\x00b")
    assert doc["title"] == "Nulled" and doc["body_md"] == "ab"
    r = await client.post(f"/api/kb/spaces/{w['org'].id}/documents", json={"title": "\x00", "body_md": ""})
    assert r.status_code == 422
    r = await client.post(f"/api/kb/spaces/{w['org'].id}/folders", json={"name": "a/b"})
    assert r.status_code == 422


async def test_viewer_and_outsider_access(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    doc = await _create(client, w["team"].id)
    await _as(client, w["viewer"])
    got = (await client.get(f"/api/kb/documents/{doc['id']}")).json()
    assert got["can_write"] is False and got["can_delete"] is False
    assert (await client.put(f"/api/kb/documents/{doc['id']}", json={"base_revision": 1, "body_md": "x"})).status_code == 403
    assert (await client.post(f"/api/kb/spaces/{w['team'].id}/documents", json={"title": "x", "body_md": ""})).status_code == 403
    await _as(client, w["outsider"])
    assert (await client.get(f"/api/kb/documents/{doc['id']}")).status_code == 404
    assert (await client.get(f"/api/kb/spaces/{w['team'].id}/tree")).status_code == 404
    assert (await client.get(f"/api/kb/documents/{doc['id']}/revisions")).status_code == 404
    kinds = {s["kind"] for s in (await client.get("/api/kb/spaces")).json()}
    assert kinds == {"org", "team"}


async def test_spaces_list_names(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    spaces = (await client.get("/api/kb/spaces")).json()
    names = {s["kind"]: s["name"] for s in spaces}
    assert names["org"] == "Organization" and names["project"] == "PAY — Project PAY"
    assert all(s["can_write"] for s in spaces)


async def test_links_parsed_and_backlinks_filtered_by_access(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    r = await client.post("/api/projects/PAY/tasks", json={"title": "t", "type": "task"})
    assert r.status_code == 201, r.text
    org_doc = await _create(client, w["org"].id, title="Org doc")
    team_doc = await _create(client, w["team"].id, title="Team doc", body=f"[[PAY-1]] [[doc:{org_doc['id']}]] [[PAY-99]]")
    links = (await db.execute(select(KbLink))).scalars().all()
    assert len(links) == 2
    back = (await client.get(f"/api/kb/documents/{org_doc['id']}/backlinks")).json()
    assert [b["id"] for b in back] == [team_doc["id"]]
    refs = (await client.get("/api/tasks/PAY-1/kb-references")).json()
    assert [x["id"] for x in refs] == [team_doc["id"]]
    # the outsider can read the org doc but not the team doc that links to it
    await _as(client, w["outsider"])
    assert (await client.get(f"/api/kb/documents/{org_doc['id']}/backlinks")).json() == []
    assert (await client.get("/api/tasks/PAY-1/kb-references")).status_code == 404
    # editing the body refreshes links
    await _as(client, w["member"])
    await client.put(f"/api/kb/documents/{team_doc['id']}", json={"base_revision": 1, "body_md": "no links"})
    assert (await client.get(f"/api/kb/documents/{org_doc['id']}/backlinks")).json() == []


async def test_resolve_hides_restricted_titles(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    secret = await _create(client, w["team"].id, title="Secret plan")
    public = await _create(client, w["org"].id, title="Public")
    missing = str(uuid.uuid4())
    await _as(client, w["outsider"])
    r = await client.post("/api/kb/resolve", json={"doc_ids": [secret["id"], public["id"], missing]})
    assert r.json() == {
        secret["id"]: {"title": None, "readable": False},
        public["id"]: {"title": "Public", "readable": True},
        missing: {"title": None, "readable": False},
    }


async def test_move_requires_write_on_both_and_hides_from_old_readers(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    doc = await _create(client, w["org"].id, title="Movable")
    # member cannot write the other team's space: it is not even visible
    r = await client.post(f"/api/kb/documents/{doc['id']}/move", json={"space_id": str(w["other"].id)})
    assert r.status_code == 404
    r = await client.post(f"/api/kb/documents/{doc['id']}/move", json={"space_id": str(w["team"].id)})
    assert r.status_code == 200 and r.json()["space"]["id"] == str(w["team"].id)
    await _as(client, w["outsider"])
    assert (await client.get(f"/api/kb/documents/{doc['id']}")).status_code == 404
    await _as(client, w["viewer"])
    r = await client.post(f"/api/kb/documents/{doc['id']}/move", json={"space_id": str(w["org"].id)})
    assert r.status_code == 403


async def test_move_into_folder_with_same_title_409(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    await _create(client, w["team"].id, title="Dup")
    doc = await _create(client, w["org"].id, title="Dup")
    r = await client.post(f"/api/kb/documents/{doc['id']}/move", json={"space_id": str(w["team"].id)})
    assert r.status_code == 409 and r.json()["detail"] == "title_taken"


async def test_delete_document_permissions(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    doc = await _create(client, w["team"].id)
    other = await make_user(db)
    from app.teams.models import TeamMember

    db.add(TeamMember(team_id=w["team_obj"].id, user_id=other.id))
    await db.commit()
    await _as(client, other)
    assert (await client.delete(f"/api/kb/documents/{doc['id']}")).status_code == 403
    await _as(client, w["manager"])
    assert (await client.delete(f"/api/kb/documents/{doc['id']}")).status_code == 204
    assert (await client.get(f"/api/kb/documents/{doc['id']}")).status_code == 404


async def test_delete_folder_non_recursive_409_recursive_moves_docs_up(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    sid = w["team"].id
    top = (await client.post(f"/api/kb/spaces/{sid}/folders", json={"name": "Top"})).json()
    sub = (await client.post(f"/api/kb/spaces/{sid}/folders", json={"name": "Sub", "parent_id": top["id"]})).json()
    r = await client.post(f"/api/kb/spaces/{sid}/folders", json={"name": "Sub", "parent_id": top["id"]})
    assert r.status_code == 409 and r.json()["detail"] == "folder_name_taken"
    inner = await _create(client, sid, title="Inner", folder_id=sub["id"])
    clash = await _create(client, sid, title="Root doc", folder_id=top["id"])
    await _create(client, sid, title="Root doc")  # same title at the root
    assert (await client.get(f"/api/kb/documents/{inner['id']}")).json()["path"] == "Top/Sub"

    r = await client.delete(f"/api/kb/folders/{top['id']}")
    assert r.status_code == 409 and r.json()["detail"] == "folder_not_empty"
    r = await client.delete(f"/api/kb/folders/{top['id']}", params={"recursive": "true"})
    assert r.status_code == 204
    tree = (await client.get(f"/api/kb/spaces/{sid}/tree")).json()
    assert tree["folders"] == []
    titles = sorted(d["title"] for d in tree["documents"])
    assert titles == ["Inner", "Root doc", "Root doc (2)"]
    assert all(d["folder_id"] is None for d in tree["documents"])
    assert (await client.get(f"/api/kb/documents/{clash['id']}")).json()["title"] == "Root doc (2)"

    f = (await client.post(f"/api/kb/spaces/{sid}/folders", json={"name": "Empty"})).json()
    r = await client.patch(f"/api/kb/folders/{f['id']}", json={"name": "Renamed"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    assert (await client.delete(f"/api/kb/folders/{f['id']}")).status_code == 204


def test_diff_ops_and_context_collapse():
    a = "\n".join(f"line {i}" for i in range(20))
    b_lines = [f"line {i}" for i in range(20)]
    b_lines[10] = "changed"
    b_lines.insert(15, "added")
    ops = diff(a, "\n".join(b_lines))
    kinds = [o["op"] for o in ops]
    assert kinds == ["collapsed", "equal", "replace", "equal", "insert", "equal"]
    assert ops[0]["count"] == 7  # lines 0-6 hidden, 7-9 kept as context
    assert ops[1]["a_lines"] == ["line 7", "line 8", "line 9"]
    assert ops[2] == {"op": "replace", "a_start": 11, "b_start": 11, "a_lines": ["line 10"], "b_lines": ["changed"]}
    assert ops[4]["b_lines"] == ["added"] and ops[4]["a_lines"] == []
    assert ops[-1]["a_lines"] == ["line 15", "line 16", "line 17", "line 18", "line 19"]
    assert diff("same", "same") == [{"op": "equal", "a_start": 1, "b_start": 1, "a_lines": ["same"], "b_lines": ["same"]}]


async def test_diff_endpoint(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    doc = await _create(client, w["org"].id, body="a\nb")
    await client.put(f"/api/kb/documents/{doc['id']}", json={"base_revision": 1, "body_md": "a\nc"})
    ops = (await client.get(f"/api/kb/documents/{doc['id']}/revisions/1/diff/2")).json()
    assert [o["op"] for o in ops] == ["equal", "replace"]
    assert (await client.get(f"/api/kb/documents/{doc['id']}/revisions/1/diff/5")).status_code == 404


async def test_delete_task_removes_its_links(client, db):
    w = await _world(client, db)
    await _as(client, w["member"])
    await client.post("/api/projects/PAY/tasks", json={"title": "t", "type": "task"})
    await _create(client, w["team"].id, body="[[PAY-1]]")
    assert (await db.execute(select(func.count()).select_from(KbLink))).scalar_one() == 1
    await _as(client, w["manager"])
    r = await client.delete("/api/tasks/PAY-1")
    assert r.status_code == 204, r.text
    assert (await db.execute(select(func.count()).select_from(KbLink))).scalar_one() == 0


def test_visible_rules():
    me, team, other_team, project = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    space = uuid.uuid4()
    teams = {team}
    assert _visible(Event(type="kb.updated", space_id=space), me, set(), teams)  # org space
    assert _visible(Event(type="kb.updated", space_id=space, team_id=team), me, set(), teams)
    assert not _visible(Event(type="kb.updated", space_id=space, team_id=other_team), me, set(), teams)
    assert _visible(Event(type="kb.updated", space_id=space, team_id=other_team), me, None, None)  # admin
    assert not _visible(Event(type="kb.updated", space_id=space, project_id=project), me, set(), teams)
    assert not _visible(Event(type="other"), me, set(), teams)


def _ws_login(tc: TestClient, user) -> None:
    r = tc.post("/api/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD})
    assert r.status_code == 200, r.text


async def test_kb_events_scoped_to_space_readers(db, tc_factory, client):
    w = await _world(client, db)
    writer, watcher = tc_factory(), tc_factory(lifespan=True)
    _ws_login(writer, w["member"])
    _ws_login(watcher, w["outsider"])
    with watcher.websocket_connect("/api/ws") as ws:
        r = writer.post(f"/api/kb/spaces/{w['team'].id}/documents", json={"title": "hidden", "body_md": ""})
        assert r.status_code == 201
        r = writer.post(f"/api/kb/spaces/{w['org'].id}/documents", json={"title": "shown", "body_md": ""})
        assert r.status_code == 201
        msg = ws.receive_json()
        assert msg["type"] == "kb.updated" and msg["space_id"] == str(w["org"].id)
