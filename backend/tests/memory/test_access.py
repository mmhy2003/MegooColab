import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.agents.models import Agent, AgentProgram
from app.auth.models import Role
from app.memory import access, entities
from app.memory.models import EntityKind, MemConclusion, MemEntity, ScopeKind
from app.teams.models import TeamMember
from tests.factories import login, make_project, make_team, make_user


async def _world(client, db):
    member = await make_user(db)
    viewer = await make_user(db, role=Role.viewer)
    outsider = await make_user(db)
    admin = await make_user(db, role=Role.admin)
    project, manager, team = await make_project(client, db, "PAY", member, viewer)
    other_team = await make_team(db, outsider)
    return {"member": member, "viewer": viewer, "outsider": outsider, "admin": admin, "manager": manager,
                "project_id": project["id"], "team": team, "other_team": other_team}


async def test_core_entities_created_once(client, db):
    w = await _world(client, db)
    await entities.ensure_core_entities(db)
    await entities.ensure_core_entities(db)
    await db.commit()
    rows = (await db.execute(select(MemEntity))).scalars().all()
    kinds = sorted(r.kind for r in rows)
    assert kinds == ["org", "project", "team", "team"]
    assert {r.team_id for r in rows if r.kind == EntityKind.team} == {w["team"].id, w["other_team"].id}


async def test_entity_names_from_rows(client, db):
    w = await _world(client, db)
    org = await entities.org_entity(db)
    project = await entities.ensure_entity(db, EntityKind.project, w["project_id"])
    person = await entities.ensure_entity(db, EntityKind.user, w["member"].id)
    agent = Agent(owner_id=w["member"].id, name="Builder", program=AgentProgram.claude_code)
    db.add(agent)
    await db.flush()
    bot = await entities.ensure_entity(db, EntityKind.agent, agent.id)
    again = await entities.ensure_entity(db, EntityKind.user, w["member"].id)
    await db.commit()
    assert (org.name, project.name, person.name, bot.name) == (
        "Organization", "PAY — Project PAY", w["member"].name, "Builder"
    )
    assert again.id == person.id and person.ref_id == w["member"].id


async def _scopes(db, user):
    return await access.readable_scopes(db, user)


async def test_readable_scopes_matrix(client, db):
    w = await _world(client, db)
    pid = w["project_id"]
    team_scope = (ScopeKind.team, w["team"].id)
    project_scope = (ScopeKind.project, pid)
    other_scope = (ScopeKind.team, w["other_team"].id)
    org = (ScopeKind.org, None)
    for who, readable in {
        "member": {org, team_scope, project_scope},
        "viewer": {org, team_scope, project_scope},
        "outsider": {org, other_scope},
        "admin": {org, team_scope, project_scope, other_scope},
    }.items():
        scopes = await _scopes(db, w[who])
        for s in (org, team_scope, project_scope, other_scope):
            assert scopes.contains(s) == (s in readable), (who, s)
            assert await access.can_read_scope(db, w[who], s) == (s in readable), (who, s)
    await db.execute(delete(TeamMember).where(TeamMember.user_id == w["member"].id))
    await db.commit()
    scopes = await _scopes(db, w["member"])
    assert not scopes.contains(team_scope) and not scopes.contains(project_scope)


async def test_readable_scopes_clause_filters_rows(client, db):
    w = await _world(client, db)
    org = await entities.org_entity(db)
    for kind, team_id, project_id in (
        (ScopeKind.org, None, None),
        (ScopeKind.team, w["other_team"].id, None),
        (ScopeKind.project, None, w["project_id"]),
    ):
        db.add(MemConclusion(entity_id=org.id, text=str(kind), kind="observed", scope_kind=kind,
                             scope_team_id=team_id, scope_project_id=project_id))
    await db.commit()
    for who, expected in (("member", {"org", "project"}), ("outsider", {"org", "team"}),
                          ("admin", {"org", "team", "project"})):
        scopes = await _scopes(db, w[who])
        rows = (await db.execute(select(MemConclusion.text).where(scopes.clause(MemConclusion)))).scalars()
        assert set(rows) == expected, who


async def test_can_edit_scope_matrix(client, db):
    w = await _world(client, db)
    org = (ScopeKind.org, None)
    team_scope = (ScopeKind.team, w["team"].id)
    project_scope = (ScopeKind.project, w["project_id"])
    other_scope = (ScopeKind.team, w["other_team"].id)
    expected = {
        "member": {team_scope, project_scope},
        "viewer": set(),
        "manager": {org, team_scope, project_scope},
        "admin": {org, team_scope, project_scope, other_scope},
        "outsider": {other_scope},
    }
    for who, allowed in expected.items():
        for s in (org, team_scope, project_scope, other_scope):
            assert await access.can_edit_scope(db, w[who], s) == (s in allowed), (who, s)


async def test_conclusion_scope_check_constraint(client, db):
    w = await _world(client, db)
    org = await entities.org_entity(db)
    db.add(MemConclusion(entity_id=org.id, text="x", kind="observed", scope_kind=ScopeKind.org,
                         scope_project_id=w["project_id"]))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_scope_rows_cascade_with_project(client, db):
    w = await _world(client, db)
    entity = await entities.ensure_entity(db, EntityKind.project, w["project_id"])
    db.add(MemConclusion(entity_id=(await entities.org_entity(db)).id, text="x", kind="observed",
                         scope_kind=ScopeKind.project, scope_project_id=w["project_id"]))
    await db.commit()
    await login(client, w["admin"])
    assert (await client.delete("/api/projects/PAY")).status_code == 204
    assert (await db.execute(select(MemConclusion))).first() is None
    assert await db.get(MemEntity, entity.id, populate_existing=True) is None


async def test_products_admin_manager_only_and_project_links_checked(client, db):
    w = await _world(client, db)
    with pytest.raises(HTTPException) as e:
        await entities.create_product(db, w["member"], "Atlas", "", [])
    assert e.value.status_code == 403
    product = await entities.create_product(db, w["manager"], "Atlas", "Billing product", [w["project_id"]])
    await db.commit()
    assert product.kind == EntityKind.product and await entities.product_project_ids(db, product.id) == {
        __import__("uuid").UUID(w["project_id"])
    }
    outsider_manager = await make_user(db, role=Role.manager)
    with pytest.raises(HTTPException) as e:
        await entities.create_product(db, outsider_manager, "Zeus", "", [w["project_id"]])
    assert e.value.status_code == 404 and e.value.detail == "project_not_found"
    renamed = await entities.update_product(db, w["admin"], product.id, name="Atlas 2", description=None,
                                            project_ids=[])
    assert renamed.name == "Atlas 2" and await entities.product_project_ids(db, product.id) == set()
    await entities.delete_product(db, w["admin"], product.id)
    await db.commit()
    assert await db.get(MemEntity, product.id, populate_existing=True) is None


async def test_new_team_and_project_get_entities(client, db):
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    team = (await client.post("/api/teams", json={"name": "Core", "description": ""})).json()
    await client.post("/api/projects", json={"key": "NEW", "name": "New", "description": "", "team_ids": [team["id"]]})
    kinds = sorted(r.kind for r in (await db.execute(select(MemEntity))).scalars())
    assert kinds == ["project", "team"]
