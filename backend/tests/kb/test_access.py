import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text

from app.auth.models import Role
from app.kb import access
from app.kb.models import KbDocument, KbSpace, SpaceKind
from app.teams.models import TeamMember
from tests.factories import login, make_project, make_team, make_user


async def _spaces(db):
    return (await db.execute(select(KbSpace))).scalars().all()


async def test_backfill_creates_org_team_project_spaces(client, db):
    team = await make_team(db)  # factory: inserted directly, no hook ran
    project, _, project_team = await make_project(client, db, "PAY")
    await db.execute(delete(KbSpace))
    await db.commit()

    await access.ensure_spaces(db)
    await access.ensure_spaces(db)  # idempotent
    await db.commit()
    spaces = await _spaces(db)
    assert sorted(s.kind for s in spaces) == ["org", "project", "team", "team"]
    assert {s.team_id for s in spaces if s.kind == SpaceKind.team} == {team.id, project_team.id}
    assert [str(s.project_id) for s in spaces if s.kind == SpaceKind.project] == [project["id"]]


async def test_new_team_and_project_get_spaces(client, db):
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    r = await client.post("/api/teams", json={"name": "Core", "description": ""})
    assert r.status_code == 201
    team_id = r.json()["id"]
    r = await client.post("/api/projects", json={"key": "NEW", "name": "New", "description": "", "team_ids": [team_id]})
    assert r.status_code == 201
    spaces = await _spaces(db)
    assert {str(s.team_id) for s in spaces if s.kind == SpaceKind.team} == {team_id}
    assert {str(s.project_id) for s in spaces if s.kind == SpaceKind.project} == {r.json()["id"]}


async def _world(client, db):
    """Two teams; project PAY belongs to team A."""
    member_a = await make_user(db)
    viewer_a = await make_user(db, role=Role.viewer)
    outsider = await make_user(db)
    admin = await make_user(db, role=Role.admin)
    project, manager_a, team_a = await make_project(client, db, "PAY", member_a, viewer_a)
    team_b = await make_team(db, outsider)
    await access.ensure_spaces(db)
    await db.commit()
    org = await access.org_space(db)
    sa = await access.space_for_team(db, team_a.id)
    sb = await access.space_for_team(db, team_b.id)
    sp = await access.space_for_project(db, project["id"])
    return {"member_a": member_a, "viewer_a": viewer_a, "outsider": outsider, "admin": admin, "manager_a": manager_a,
                "org": org, "team_a": sa, "team_b": sb, "project": sp, "team_a_obj": team_a}


async def test_access_matrix(client, db):
    w = await _world(client, db)
    expect = {
        # user: (readable spaces, writable spaces)
        "member_a": ({"org", "team_a", "project"}, {"org", "team_a", "project"}),
        "viewer_a": ({"org", "team_a", "project"}, set()),
        "outsider": ({"org", "team_b"}, {"org", "team_b"}),
        "admin": ({"org", "team_a", "team_b", "project"}, {"org", "team_a", "team_b", "project"}),
    }
    names = ["org", "team_a", "team_b", "project"]
    for who, (readable, writable) in expect.items():
        user = w[who]
        ids = await access.readable_space_ids(db, user)
        assert {n for n in names if w[n].id in ids} == readable, who
        for n in names:
            assert await access.can_read(db, user, w[n]) == (n in readable), (who, n)
            assert await access.can_write(db, user, w[n]) == (n in writable), (who, n)


async def test_can_delete_document(client, db):
    w = await _world(client, db)
    doc = KbDocument(space_id=w["team_a"].id, title="T", body_md="", latest_revision=1, created_by=w["member_a"].id)
    db.add(doc)
    await db.commit()
    other = await make_user(db)
    db.add(TeamMember(team_id=w["team_a_obj"].id, user_id=other.id))
    await db.commit()
    assert await access.can_delete_document(db, w["member_a"], doc)  # creator
    assert await access.can_delete_document(db, w["manager_a"], doc)  # team manager
    assert await access.can_delete_document(db, w["admin"], doc)
    assert not await access.can_delete_document(db, other, doc)  # writer, not creator
    assert not await access.can_delete_document(db, w["viewer_a"], doc)
    assert not await access.can_delete_document(db, w["outsider"], doc)


async def test_losing_team_membership_removes_access(client, db):
    w = await _world(client, db)
    user = w["member_a"]
    assert w["project"].id in await access.readable_space_ids(db, user)
    await db.execute(delete(TeamMember).where(TeamMember.user_id == user.id))
    await db.commit()
    ids = await access.readable_space_ids(db, user)
    assert w["project"].id not in ids and w["team_a"].id not in ids
    assert not await access.can_read(db, user, w["project"])


async def test_unreadable_space_is_404_not_403(client, db):
    w = await _world(client, db)
    with pytest.raises(HTTPException) as e:
        await access.get_space_for(db, w["outsider"], w["team_a"].id)
    assert e.value.status_code == 404 and e.value.detail == "space_not_found"
    with pytest.raises(HTTPException) as e:
        await access.get_space_for(db, w["outsider"], w["team_a"].id, write=True)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await access.get_space_for(db, w["viewer_a"], w["team_a"].id, write=True)
    assert e.value.status_code == 403
    assert (await access.get_space_for(db, w["viewer_a"], w["team_a"].id)).id == w["team_a"].id

    doc = KbDocument(space_id=w["team_a"].id, title="T", body_md="", latest_revision=1, created_by=w["member_a"].id)
    db.add(doc)
    await db.commit()
    with pytest.raises(HTTPException) as e:
        await access.get_document_for(db, w["outsider"], doc.id)
    assert e.value.status_code == 404 and e.value.detail == "document_not_found"
    got, space = await access.get_document_for(db, w["member_a"], doc.id, write=True)
    assert got.id == doc.id and space.id == w["team_a"].id


async def test_space_deleted_with_project(client, db):
    w = await _world(client, db)
    db.add(KbDocument(space_id=w["project"].id, title="T", body_md="", latest_revision=1))
    await db.commit()
    await login(client, w["admin"])
    assert (await client.delete("/api/projects/PAY")).status_code == 204
    assert await db.get(KbSpace, w["project"].id, populate_existing=True) is None
    assert (await db.execute(select(KbDocument))).first() is None


async def test_org_space_is_a_singleton(db):
    a = await access.org_space(db)
    b = await access.org_space(db)
    await db.commit()
    assert a.id == b.id
    assert len([s for s in await _spaces(db) if s.kind == SpaceKind.org]) == 1


async def test_vector_extension_present(db):
    assert (await db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))).scalar_one() == "vector"
