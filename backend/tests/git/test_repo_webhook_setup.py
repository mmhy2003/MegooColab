"""A repository's Webhook dialog (piece 1): its address and status, its secret on request, a new one, and Create it
for me, which never duplicates and never touches a webhook pointing elsewhere."""

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.crypto import encrypt
from app.core.db import SessionLocal
from app.git import providers, service
from app.git.models import GitConnection
from app.projects.models import Project, ProjectRepository
from tests.factories import login, make_project, make_user

TOKEN = "ghp_SetupToken"


class FakeGitHub:
    """GitHub's hooks API for acme/pay, in memory: hooks id -> url; calls recorded; `refuse` answers that status."""

    def __init__(self):
        self.hooks: dict[str, dict] = {}
        self.calls: list[tuple[str, str, object]] = []
        self.refuse: int | None = None
        self.next_id = 100

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if self.refuse:
            return httpx.Response(self.refuse, json={"message": "x"})
        if path == "/repos/acme/pay/hooks" and request.method == "GET":
            return httpx.Response(200, json=[{"id": int(i), "config": {"url": h["url"]}} for i, h in self.hooks.items()])
        if path == "/repos/acme/pay/hooks" and request.method == "POST":
            self.next_id += 1
            self.hooks[str(self.next_id)] = {"url": body["config"]["url"], "secret": body["config"]["secret"]}
            return httpx.Response(201, json={"id": self.next_id})
        if path.startswith("/repos/acme/pay/hooks/"):
            hook = path.rsplit("/", 1)[1]
            if hook not in self.hooks:
                return httpx.Response(404, json={"message": "Not Found"})
            if request.method == "PATCH":
                self.hooks[hook] = {"url": body["config"]["url"], "secret": body["config"]["secret"]}
                return httpx.Response(200, json={"id": int(hook)})
            if request.method == "DELETE":
                del self.hooks[hook]
                return httpx.Response(204)
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def github(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(providers, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    return fake


async def _world(client, db, *members):
    await make_project(client, db, "PAY", *members)
    project = (await db.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
    conn = GitConnection(name="GitHub", kind="github", base_url="https://github.com", token_enc=encrypt(TOKEN))
    db.add(conn)
    await db.flush()
    repo = ProjectRepository(project_id=project.id, name="acme/pay", url="https://github.com/acme/pay", provider="github",
                             connection_id=conn.id)
    db.add(repo)
    await db.commit()
    return conn, repo


def _base(repo) -> str:
    return f"/api/projects/PAY/repositories/{repo.id}/webhook"


async def _row(repo_id) -> ProjectRepository:
    async with SessionLocal() as s:
        return await s.get(ProjectRepository, repo_id)


async def test_the_dialog_gets_address_and_status_but_not_the_secret(client, db, github):
    _, repo = await _world(client, db)
    r = await client.get(_base(repo))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["url"] == service.webhook_url(repo.id) and out["kind"] == "github"
    assert out["hook_page_url"] == "https://github.com/acme/pay/settings/hooks"
    assert (out["status"], out["installed"], out["public_url_is_default"]) == ("not_set_up", False, True)
    assert "secret" not in out
    assert (await _row(repo.id)).webhook_secret_enc  # made on first use


async def test_the_secret_is_shown_on_request_and_renewed(client, db, github):
    _, repo = await _world(client, db)
    await client.get(_base(repo))
    first = (await client.get(f"{_base(repo)}/secret")).json()["secret"]
    assert len(first) >= 40
    renewed = (await client.post(f"{_base(repo)}/secret")).json()
    assert renewed["secret"] != first and renewed["host_updated"] is None
    assert (await client.get(f"{_base(repo)}/secret")).json()["secret"] == renewed["secret"]


async def test_install_creates_when_none_exists(client, db, github):
    _, repo = await _world(client, db)
    r = await client.post(f"{_base(repo)}/install")
    assert r.status_code == 200 and r.json() == {"installed": True}
    (hook_id, hook), = github.hooks.items()
    assert hook["url"] == service.webhook_url(repo.id)
    assert hook["secret"] == (await client.get(f"{_base(repo)}/secret")).json()["secret"]
    assert (await _row(repo.id)).webhook_hook_id == hook_id
    assert (await client.get(_base(repo))).json()["installed"] is True


async def test_install_updates_ours_removes_the_shared_one_and_leaves_others(client, db, github):
    conn, repo = await _world(client, db)
    github.hooks = {"1": {"url": service.webhook_url(repo.id), "secret": "old"},
                    "2": {"url": service.shared_webhook_url(conn.id), "secret": "shared"},
                    "3": {"url": "https://ci.example/hook", "secret": "theirs"}}
    assert (await client.post(f"{_base(repo)}/install")).status_code == 200
    methods = [(m, p) for m, p, _ in github.calls if m != "GET"]
    assert ("PATCH", "/repos/acme/pay/hooks/1") in methods and ("DELETE", "/repos/acme/pay/hooks/2") in methods
    assert all(not p.endswith("/3") for _, p in methods) and ("POST", "/repos/acme/pay/hooks") not in methods
    assert set(github.hooks) == {"1", "3"} and github.hooks["3"]["secret"] == "theirs"
    assert (await _row(repo.id)).webhook_hook_id == "1"


async def test_install_without_permission_says_forbidden(client, db, github):
    _, repo = await _world(client, db)
    github.refuse = 403
    r = await client.post(f"{_base(repo)}/install")
    assert (r.status_code, r.json()["detail"]) == (422, "forbidden")
    github.refuse = None
    assert (await client.get(_base(repo))).status_code == 200  # the manual steps still work


async def test_renewing_updates_our_hook_on_the_host(client, db, github):
    _, repo = await _world(client, db)
    await client.post(f"{_base(repo)}/install")
    renewed = (await client.post(f"{_base(repo)}/secret")).json()
    assert renewed["host_updated"] is True
    (hook,) = github.hooks.values()
    assert hook["secret"] == renewed["secret"]
    github.refuse = 500
    assert (await client.post(f"{_base(repo)}/secret")).json()["host_updated"] is False


async def test_members_get_403_and_unconnected_repositories_422(client, client_factory, db, github):
    member = await make_user(db)
    _, repo = await _world(client, db, member)
    m = client_factory()
    await login(m, member)
    assert (await m.get(_base(repo))).status_code == 403
    assert (await m.get(f"{_base(repo)}/secret")).status_code == 403
    plain = (await client.post("/api/projects/PAY/repositories",
                               json={"name": "p", "url": "https://git.example/p", "provider": "plain"})).json()
    r = await client.get(f"/api/projects/PAY/repositories/{plain['id']}/webhook")
    assert (r.status_code, r.json()["detail"]) == (422, "repository_not_connected")
