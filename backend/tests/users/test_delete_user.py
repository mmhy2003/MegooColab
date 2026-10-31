"""Deleting someone: what is theirs goes, the team's work stays (shown as Someone); and the admin users list."""

import uuid

import pyotp
from sqlalchemy import select

from app.agent_runs.models import AgentRun
from app.agents.models import Agent
from app.audit.models import AuditLog
from app.auth.models import PersonalAccessToken, Role, User, UserStatus
from app.core.db import SessionLocal
from app.tasks.models import Comment, Task
from app.teams.models import TeamMember
from tests.auth.test_passkeys import add_passkey
from tests.factories import login, make_project, make_user


async def _world(client, client_factory, db):
    """A project PAY with a member who reported a task, is assigned another, commented, has an agent and a token,
    and started a run on the manager's agent. Returns (member, manager, admin_client, tasks)."""
    member = await make_user(db, email="gone@x.io", name="Gil Gone")
    project, manager, _team = await make_project(client, db, "PAY", member)
    mc = client_factory()
    await login(mc, member)
    reported = (await mc.post("/api/projects/PAY/tasks", json={"title": "Reported by Gil"})).json()
    assigned = (await client.post("/api/projects/PAY/tasks",
                                  json={"title": "Gil's job", "assignee_user_id": str(member.id)})).json()
    assert (await mc.post(f"/api/tasks/{assigned['key']}/comments", json={"body_md": "On it"})).status_code == 201
    assert (await mc.post("/api/agents", json={"program": "claude_code"})).status_code == 201
    assert (await mc.post("/api/tokens", json={"name": "laptop", "scopes": ["mcp"]})).status_code == 201
    managers_agent = (await client.post("/api/agents", json={"program": "codex"})).json()
    async with SessionLocal() as s:
        s.add(AgentRun(task_id=uuid.UUID(assigned["id"]), agent_id=uuid.UUID(managers_agent["id"]),
                       requested_by=member.id, policy="read_only", prompt="p", status="completed"))
        await s.commit()
    admin = client_factory()
    await login(admin, await make_user(db, role=Role.admin, name="Ada Admin"))
    return member, manager, admin, mc, (reported, assigned)


async def test_deleting_someone_removes_what_is_theirs_and_keeps_the_teams_work(client, client_factory, db):
    member, _manager, admin, member_client, (reported, assigned) = await _world(client, client_factory, db)
    r = await admin.delete(f"/api/admin/users/{member.id}")
    assert r.status_code == 204, r.text
    assert (await member_client.get("/api/auth/me")).status_code == 401  # signed out everywhere
    async with SessionLocal() as s:
        assert await s.get(User, member.id) is None
        assert (await s.execute(select(Agent).where(Agent.owner_id == member.id))).scalars().all() == []
        assert (await s.execute(select(PersonalAccessToken).where(PersonalAccessToken.user_id == member.id))).scalars().all() == []
        assert (await s.execute(select(TeamMember).where(TeamMember.user_id == member.id))).scalars().all() == []
        kept = await s.get(Task, uuid.UUID(reported["id"]))
        assert kept is not None and kept.reporter_id is None
        unassigned = await s.get(Task, uuid.UUID(assigned["id"]))
        assert unassigned.assignee_user_id is None
        [comment] = (await s.execute(select(Comment).where(Comment.task_id == unassigned.id))).scalars().all()
        assert (comment.body_md, comment.author_user_id) == ("On it", None)
        [run] = (await s.execute(select(AgentRun).where(AgentRun.task_id == unassigned.id))).scalars().all()
        assert run.requested_by is None  # the task's history keeps the run
        [entry] = (await s.execute(select(AuditLog).where(AuditLog.action == "user.deleted"))).scalars().all()
    assert entry.data == {"email": "gone@x.io", "name": "Gil Gone"}
    assert entry.target_id == member.id


async def test_an_invited_person_can_be_deleted(client, db):
    await login(client, await make_user(db, role=Role.admin))
    invited = await make_user(db, status=UserStatus.invited)
    assert (await client.delete(f"/api/admin/users/{invited.id}")).status_code == 204
    async with SessionLocal() as s:
        assert await s.get(User, invited.id) is None


async def test_not_oneself_and_only_admins(client, client_factory, db):
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    r = await client.delete(f"/api/admin/users/{admin.id}")
    assert r.status_code == 409 and r.json()["detail"] == "cannot_delete_self"
    other = await make_user(db)
    manager = client_factory()
    await login(manager, await make_user(db, role=Role.manager))
    assert (await manager.delete(f"/api/admin/users/{other.id}")).status_code == 403
    assert (await client.delete(f"/api/admin/users/{uuid.uuid4()}")).status_code == 404


async def test_the_admin_list_shows_two_factor_and_last_sign_in(client, client_factory, db):
    both = await make_user(db, name="Bo Both")
    bc = client_factory()
    await login(bc, both)
    await add_passkey(bc)
    await add_passkey(bc, name="Second")
    secret = (await bc.post("/api/auth/totp/setup")).json()["secret"]
    await bc.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()})
    never = await make_user(db, status=UserStatus.invited)
    await login(client, await make_user(db, role=Role.admin))
    rows = {r["user_id"]: r for r in (await client.get("/api/admin/users/details")).json()}
    assert rows[str(both.id)]["totp"] is True and rows[str(both.id)]["passkeys"] == 2
    assert rows[str(both.id)]["last_login_at"] is not None
    assert rows[str(never.id)] == {"user_id": str(never.id), "totp": False, "passkeys": 0, "last_login_at": None}
    manager = client_factory()
    await login(manager, await make_user(db, role=Role.manager))
    assert (await manager.get("/api/admin/users/details")).status_code == 403
