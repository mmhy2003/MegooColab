"""Fields the screens use to offer only what a person may do: team membership and a team's real project count."""

from app.auth.models import Role
from tests.factories import login, make_project, make_team, make_user


async def test_team_list_says_is_member(client, db):
    _project, manager, team_a = await make_project(client, db, "PAY")
    other = await make_user(db, role=Role.manager)
    team_b = await make_team(db, other)
    teams = {t["id"]: t for t in (await client.get("/api/teams")).json()}
    assert teams[str(team_a.id)]["is_member"] is True
    assert teams[str(team_b.id)]["is_member"] is False


async def test_team_detail_counts_all_projects(client, db, client_factory):
    _p, manager, team = await make_project(client, db, "PAY")
    r = await client.post("/api/projects", json={"key": "OPS", "name": "Ops", "description": "",
                                                 "team_ids": [str(team.id)]})
    assert r.status_code == 201, r.text
    assert (await client.get(f"/api/teams/{team.id}")).json()["project_count"] == 2
    outsider = await make_user(db, role=Role.member)  # sees neither project
    c2 = client_factory()
    await login(c2, outsider)
    detail = (await c2.get(f"/api/teams/{team.id}")).json()
    assert detail["project_count"] == 2 and detail["projects"] == []


async def test_project_counts_for_one_team_count_only_that_team(client, db):
    from app.teams import service

    _p, _manager, team = await make_project(client, db, "PAY")
    _q, _other, other_team = await make_project(client, db, "OPS")
    assert await service.team_project_counts(db, [team.id]) == {team.id: 1}
    assert (await service.team_project_counts(db))[other_team.id] == 1
