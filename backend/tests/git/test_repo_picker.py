"""Picking a project's repository from its provider's list (piece 1): managers only; the token never leaves."""

import httpx
import pytest

from app.core.crypto import encrypt
from app.git import providers
from app.git.models import GitConnection
from tests.factories import login, make_project, make_user

TOKEN = "ghp_PickerToken"
REPOS = [{"full_name": "acme/pay", "html_url": "https://github.com/acme/pay", "default_branch": "main"},
         {"full_name": "acme/web", "html_url": "https://github.com/acme/web", "default_branch": "develop"}]


@pytest.fixture
def host(monkeypatch):
    """A mock GitHub listing REPOS for the token; `status` makes it answer that instead."""
    state = {"status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"message": "x"})
        if request.url.path == "/user/repos" and request.headers.get("Authorization") == f"Bearer {TOKEN}":
            return httpx.Response(200, json=REPOS)
        return httpx.Response(404, json={"message": "Not Found"})

    monkeypatch.setattr(providers, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return state


async def _connection(db) -> GitConnection:
    conn = GitConnection(name="GitHub", kind="github", base_url="https://github.com", token_enc=encrypt(TOKEN))
    db.add(conn)
    await db.commit()
    return conn


async def test_a_manager_lists_a_connections_repositories(client, db, host):
    await make_project(client, db, "PAY")
    conn = await _connection(db)
    r = await client.get(f"/api/projects/PAY/repositories/choices?connection_id={conn.id}&q=pay")
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [{"path": "acme/pay", "url": "https://github.com/acme/pay", "default_branch": "main"}],
                        "more": False}


async def test_members_cannot_list_and_the_token_never_leaves(client, client_factory, db, host):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    conn = await _connection(db)
    r = await client.get(f"/api/projects/PAY/repositories/choices?connection_id={conn.id}")
    assert r.status_code == 200 and TOKEN not in r.text
    m = client_factory()
    await login(m, member)
    assert (await m.get(f"/api/projects/PAY/repositories/choices?connection_id={conn.id}")).status_code == 403


async def test_a_provider_refusal_is_a_502_with_its_code(client, db, host):
    await make_project(client, db, "PAY")
    conn = await _connection(db)
    host["status"] = 401
    r = await client.get(f"/api/projects/PAY/repositories/choices?connection_id={conn.id}")
    assert (r.status_code, r.json()["detail"]) == (502, "unauthorized")


async def test_an_unknown_connection_is_404(client, db, host):
    import uuid

    await make_project(client, db, "PAY")
    r = await client.get(f"/api/projects/PAY/repositories/choices?connection_id={uuid.uuid4()}")
    assert (r.status_code, r.json()["detail"]) == (404, "git_connection_not_found")
