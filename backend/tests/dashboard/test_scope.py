"""The scope switch: Mine, My teams (the default), Everything (admins only)."""

from app.teams.models import TeamMember
from tests.dashboard.conftest import dash
from tests.factories import login


async def test_all_is_for_admins_only(client, db, world):
    await login(client, world.viewer)
    assert (await client.get("/api/dashboard", params={"scope": "all"})).status_code == 403
    assert (await client.get("/api/dashboard", params={"scope": "nope"})).status_code == 422
    await login(client, world.admin)
    body = await dash(client, "all")
    assert body["scope"] == "all" and [p["key"] for p in body["projects"]] == ["PAY", "WEB"]


async def test_teams_is_the_default_and_means_the_viewers_projects(client, db, world):
    await login(client, world.viewer)
    body = await dash(client)
    assert body["scope"] == "teams" and [p["key"] for p in body["projects"]] == ["PAY"]


async def test_teams_for_an_admin_is_the_admins_teams(client, db, world):
    db.add(TeamMember(team_id=world.pay_team.id, user_id=world.admin.id))
    await db.commit()
    await login(client, world.admin)
    assert [p["key"] for p in (await dash(client, "teams"))["projects"]] == ["PAY"]


async def test_admin_in_no_team_gets_an_empty_teams_view(client, db, world):
    await login(client, world.admin)
    body = await dash(client, "teams")
    assert body["projects"] == [] and body["numbers"]["open_tasks"] == 0 and body["needs"] == []


async def test_system_is_null_for_non_admins(client, db, world):
    await login(client, world.viewer)
    assert (await dash(client))["system"] is None
