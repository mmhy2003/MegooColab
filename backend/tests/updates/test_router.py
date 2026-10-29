"""GET /api/updates, and the runner version that comes with each agent."""

from types import SimpleNamespace

import pytest

from app.auth.models import Role
from app.core.config import get_settings
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.runner.registry import registry
from tests.factories import login, make_project, make_user

APP_URL = "https://github.com/mmhy2003/MegooColab/releases/tag/v0.2.0"
RUNNER_URL = "https://github.com/mmhy2003/MegooColab/releases/tag/runner-v0.1.1"


@pytest.fixture
async def stored(db):
    db.add(OrgSettings(id=ORG_SETTINGS_ID, name="Acme", latest_app_version="0.2.0", latest_app_url=APP_URL,
                       latest_runner_version="0.1.1", latest_runner_url=RUNNER_URL))
    await db.commit()


async def _updates(client, db, monkeypatch, *, role: Role, app_version: str) -> dict:
    monkeypatch.setattr(get_settings(), "app_version", app_version)
    await login(client, await make_user(db, role=role))
    r = await client.get("/api/updates")
    assert r.status_code == 200, r.text
    return r.json()


async def test_an_admin_is_told_of_a_newer_server(client, db, monkeypatch, stored):
    body = await _updates(client, db, monkeypatch, role=Role.admin, app_version="0.1.0")
    assert body == {"app": {"current": "0.1.0", "latest": "0.2.0", "url": APP_URL},
                    "runner": {"latest": "0.1.1", "url": RUNNER_URL}}


async def test_a_member_is_not_told_of_the_server(client, db, monkeypatch, stored):
    body = await _updates(client, db, monkeypatch, role=Role.member, app_version="0.1.0")
    assert body == {"app": None, "runner": {"latest": "0.1.1", "url": RUNNER_URL}}


@pytest.mark.parametrize("app_version", ["dev", "0.2.0", "0.3.0"])
async def test_no_pill_from_source_or_when_up_to_date(client, db, monkeypatch, stored, app_version):
    body = await _updates(client, db, monkeypatch, role=Role.admin, app_version=app_version)
    assert body["app"] is None


async def test_nothing_known_yet(client, db, monkeypatch):
    db.add(OrgSettings(id=ORG_SETTINGS_ID, name="Acme"))
    await db.commit()
    assert await _updates(client, db, monkeypatch, role=Role.admin, app_version="0.1.0") == {"app": None, "runner": None}


async def test_an_agent_carries_its_runners_version(client, db, monkeypatch):
    me = await make_user(db)
    await make_project(client, db, "PAY", me)
    await login(client, me)
    r = await client.post("/api/agents", json={"program": "claude_code"})
    agent = r.json()
    r = await client.put(f"/api/agents/{agent['id']}/bindings",
                         json={"bindings": [{"project_ref": "PAY", "local_path": "/repo"}]})
    assert r.status_code == 200, r.text
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "T", "assignee_agent_id": agent["id"]})).json()

    async def views() -> list:
        mine = (await client.get("/api/agents/mine")).json()[0]["runner"]
        assignee = (await client.get(f"/api/tasks/{task['key']}")).json()["assignee_agent"]["runner"]
        dash = (await client.get("/api/dashboard", params={"scope": "mine"})).json()["agents"][0]
        assert dash["owner_id"] == str(me.id)
        return [mine, assignee, dash["runner"]]

    assert await views() == [None] * 3  # offline
    live = SimpleNamespace(version="0.1.0", os="windows", problems={}, capabilities={"workflow/1", "branch/1"})
    monkeypatch.setattr(registry, "conn_for_user", lambda user_id: live if user_id == me.id else None)
    monkeypatch.setattr(registry, "available_agents", lambda user_id: set())
    assert await views() == [{"version": "0.1.0", "os": "windows"}] * 3
