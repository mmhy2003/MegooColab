import pytest

from app.auth.models import Role, UserStatus
from tests.factories import login, make_user


async def _admin_client(client, db):
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    return admin


async def test_deactivate_revokes_sessions_immediately(client, client_factory, db):
    await _admin_client(client, db)
    u = await make_user(db)
    b = client_factory()
    await login(b, u)
    assert (await b.get("/api/auth/me")).status_code == 200
    assert (await client.post(f"/api/admin/users/{u.id}/deactivate")).status_code == 204
    assert (await b.get("/api/auth/me")).status_code == 401
    assert (await b.post("/api/auth/login", json={"email": u.email, "password": "correct-horse-1"})).status_code == 401


async def test_reactivate_allows_login_again(client, client_factory, db):
    await _admin_client(client, db)
    u = await make_user(db, status=UserStatus.deactivated)
    assert (await client.post(f"/api/admin/users/{u.id}/reactivate")).status_code == 204
    b = client_factory()
    await login(b, u)


async def test_cannot_deactivate_self(client, db):
    admin = await _admin_client(client, db)
    r = await client.post(f"/api/admin/users/{admin.id}/deactivate")
    assert r.status_code == 409


async def test_cannot_demote_last_admin(client, db):
    admin = await _admin_client(client, db)
    r = await client.patch(f"/api/admin/users/{admin.id}", json={"role": "manager"})
    assert r.status_code == 409 and r.json()["detail"] == "last_admin"
    other = await make_user(db, role=Role.admin)
    r = await client.patch(f"/api/admin/users/{other.id}", json={"role": "manager", "name": "Demoted"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "manager" and r.json()["user"]["name"] == "Demoted"


async def test_list_users_for_any_signed_in_user(client, db):
    u = await make_user(db, name="Alice Smith")
    await make_user(db, name="Bob Jones")
    await login(client, u)
    r = await client.get("/api/users", params={"q": "ali"})
    assert [x["name"] for x in r.json()] == ["Alice Smith"]


async def test_audit_lists_login_and_role_change(client, db):
    await _admin_client(client, db)
    other = await make_user(db)
    await client.patch(f"/api/admin/users/{other.id}", json={"role": "viewer"})
    r = await client.get("/api/admin/audit")
    actions = [e["action"] for e in r.json()]
    assert actions[0] == "user.role_changed" and "auth.login" in actions
    r = await client.get("/api/admin/audit", params={"action": "auth.login"})
    assert {e["action"] for e in r.json()} == {"auth.login"}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/admin/audit"),
        ("get", "/api/admin/settings"),
        ("put", "/api/admin/settings"),
        ("post", "/api/admin/settings/test-email"),
        ("patch", "/api/admin/users/00000000-0000-0000-0000-000000000000"),
        ("post", "/api/admin/users/00000000-0000-0000-0000-000000000000/deactivate"),
        ("post", "/api/admin/users/00000000-0000-0000-0000-000000000000/reactivate"),
    ],
)
async def test_non_admin_forbidden(client, db, method, path):
    m = await make_user(db, role=Role.manager)
    await login(client, m)
    r = await client.request(method.upper(), path, json={})
    assert r.status_code == 403
