from app.auth.models import Role
from tests.factories import login, make_project, make_team, make_user


async def _agent(client, **body):
    body.setdefault("program", "claude_code")
    r = await client.post("/api/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_register_agent_defaults_name(client, db):
    ahmed = await make_user(db, name="Ahmed")
    await login(client, ahmed)
    a = await _agent(client)
    assert a["name"] == "Ahmed's Claude Code"
    assert a["answer_mode"] == "manual" and a["max_concurrent_runs"] == 1
    assert a["status"] == "offline" and a["owner"]["id"] == str(ahmed.id)
    b = await _agent(client, program="codex", name="  ")
    assert b["name"] == "Ahmed's Codex"
    mine = (await client.get("/api/agents/mine")).json()
    assert {x["name"] for x in mine} == {"Ahmed's Claude Code", "Ahmed's Codex"}


async def test_bind_requires_project_access_and_absolute_path(client, db):
    me = await make_user(db)
    project, _, _ = await make_project(client, db, "PAY", me)
    other, _, _ = await make_project(client, db, "OTH")
    await login(client, me)
    a = await _agent(client)
    url = f"/api/agents/{a['id']}/bindings"

    r = await client.put(url, json={"bindings": [{"project_ref": "OTH", "local_path": "/repo"}]})
    assert r.status_code == 422 and r.json()["detail"] == "project_not_accessible"
    for bad in ("repo", "relative/path", "C:repo", "~/repo", ""):
        r = await client.put(url, json={"bindings": [{"project_ref": "PAY", "local_path": bad}]})
        assert r.status_code == 422 and r.json()["detail"] == "local_path_not_absolute", bad
    for good in ("C:\\code\\pay", "C:/code/pay", "\\\\server\\share\\pay", "/home/me/pay"):
        r = await client.put(url, json={"bindings": [{"project_ref": "PAY", "local_path": good}]})
        assert r.status_code == 200, good
        assert r.json()["bindings"][0]["local_path"] == good
    r = await client.put(url, json={"bindings": []})
    assert r.json()["bindings"] == []


async def test_local_path_hidden_from_non_owners(client, client_factory, db):
    me = await make_user(db)
    teammate = await make_user(db)
    project, manager, _ = await make_project(client, db, "PAY", me, teammate)
    await login(client, me)
    a = await _agent(client)
    await client.put(
        f"/api/agents/{a['id']}/bindings",
        json={"bindings": [{"project_ref": "PAY", "local_path": "/home/me/pay"}]},
    )
    own = (await client.get("/api/projects/PAY/agents")).json()
    assert own[0]["bindings"][0]["local_path"] == "/home/me/pay"
    assert own[0]["bindings"][0]["project_key"] == "PAY"

    other = client_factory()
    await login(other, teammate)
    seen = (await other.get("/api/projects/PAY/agents")).json()
    assert seen[0]["bindings"][0]["local_path"] is None
    assert "/home/me/pay" not in (await other.get("/api/projects/PAY/agents")).text


async def test_project_agents_list_shows_can_use(client, client_factory, db):
    owner = await make_user(db)
    member = await make_user(db)
    admin = await make_user(db, role=Role.admin)
    project, manager, _ = await make_project(client, db, "PAY", owner, member)
    outsider_mgr = await make_user(db, role=Role.manager)
    await make_team(db, outsider_mgr)

    await login(client, owner)
    a = await _agent(client)
    await client.put(
        f"/api/agents/{a['id']}/bindings",
        json={"bindings": [{"project_ref": "PAY", "local_path": "/r"}]},
    )

    async def can_use(user):
        c = client_factory()
        await login(c, user)
        r = await c.get("/api/projects/PAY/agents")
        return r.status_code, (r.json()[0]["can_use"] if r.status_code == 200 else None)

    assert await can_use(owner) == (200, True)
    assert await can_use(manager) == (200, True)
    assert await can_use(member) == (200, False)
    assert await can_use(admin) == (200, True)
    assert (await can_use(outsider_mgr))[0] == 404


async def test_only_owner_edits_agent(client, client_factory, db):
    owner = await make_user(db)
    admin = await make_user(db, role=Role.admin)
    await login(client, owner)
    a = await _agent(client)
    r = await client.patch(
        f"/api/agents/{a['id']}",
        json={"name": "Renamed", "answer_mode": "auto", "max_concurrent_runs": 3},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed" and r.json()["answer_mode"] == "auto"
    assert r.json()["max_concurrent_runs"] == 3
    assert (await client.patch(f"/api/agents/{a['id']}", json={"max_concurrent_runs": 4})).status_code == 422
    assert (await client.patch(f"/api/agents/{a['id']}", json={"max_concurrent_runs": 0})).status_code == 422

    other = client_factory()
    await login(other, admin)
    assert (await other.patch(f"/api/agents/{a['id']}", json={"name": "X"})).status_code == 404
    assert (await other.delete(f"/api/agents/{a['id']}")).status_code == 404
    assert (await other.put(f"/api/agents/{a['id']}/bindings", json={"bindings": []})).status_code == 404

    assert (await client.delete(f"/api/agents/{a['id']}")).status_code == 204
    assert (await client.get("/api/agents/mine")).json() == []


async def test_duplicate_agent_name_409(client, client_factory, db):
    me = await make_user(db, name="Sam")
    await login(client, me)
    await _agent(client)
    r = await client.post("/api/agents", json={"program": "claude_code"})
    assert r.status_code == 409 and r.json()["detail"] == "agent_name_taken"
    b = await _agent(client, program="codex")
    r = await client.patch(f"/api/agents/{b['id']}", json={"name": "Sam's Claude Code"})
    assert r.status_code == 409
    # another owner may reuse a name
    other = client_factory()
    await login(other, await make_user(db, name="Sam"))
    assert (await other.post("/api/agents", json={"program": "claude_code"})).status_code == 201


async def test_team_detail_lists_member_agents(client, client_factory, db):
    member = await make_user(db, name="Mia")
    outsider = await make_user(db, name="Zed")
    project, manager, team = await make_project(client, db, "PAY", member)
    await login(client, member)
    a = await _agent(client)
    await client.put(
        f"/api/agents/{a['id']}/bindings",
        json={"bindings": [{"project_ref": "PAY", "local_path": "/secret/path"}]},
    )
    oc = client_factory()
    await login(oc, outsider)
    await _agent(oc)

    mc = client_factory()
    await login(mc, manager)
    detail = (await mc.get(f"/api/teams/{team.id}")).json()
    assert [x["name"] for x in detail["agents"]] == ["Mia's Claude Code"]
    assert detail["agents"][0]["bindings"][0]["local_path"] is None
    assert detail["agents"][0]["owner"]["id"] == str(member.id)


async def test_admin_agents_overview_admin_only(client, client_factory, db):
    owner = await make_user(db)
    admin = await make_user(db, role=Role.admin)
    await login(client, owner)
    await _agent(client)
    assert (await client.get("/api/admin/agents")).status_code == 403
    ac = client_factory()
    await login(ac, admin)
    rows = (await ac.get("/api/admin/agents")).json()
    assert len(rows) == 1
    assert rows[0]["owner"]["id"] == str(owner.id)
    assert rows[0]["status"] == "offline" and rows[0]["current_run"] is None


async def test_can_use_agent_rule(client, db):
    from app.agents.models import Agent
    from app.agents.service import can_use_agent, may_use_agent
    from app.projects.models import Project

    owner = await make_user(db)
    member = await make_user(db)
    admin = await make_user(db, role=Role.admin)
    outside_mgr = await make_user(db, role=Role.manager)
    await make_team(db, outside_mgr)
    project_json, manager, _ = await make_project(client, db, "PAY", owner, member)
    project = await db.get(Project, __import__("uuid").UUID(project_json["id"]))
    agent = Agent(owner_id=owner.id, name="A", program="codex")
    db.add(agent)
    await db.commit()

    assert await can_use_agent(db, owner, agent, project) is True
    assert await can_use_agent(db, admin, agent, project) is True
    assert await can_use_agent(db, manager, agent, project) is True
    assert await can_use_agent(db, outside_mgr, agent, project) is False
    assert await can_use_agent(db, member, agent, project) is False
    assert may_use_agent(member, owner.id, manages=False) is False
    assert may_use_agent(admin, owner.id, manages=False) is True
