"""Notifications (NOT-1, NOT-2): the centre, preferences, email, and the `assigned` trigger."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.audit.models import AuditLog
from app.auth.models import Role, User, UserStatus
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.email import OutboxMailer
from app.jobs.models import Job
from app.notifications import jobs as notify_jobs
from app.notifications import service
from app.notifications.models import Kind, Notification
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.teams.models import TeamMember
from tests.factories import login, make_project, make_user


async def _rows(user_id) -> list[Notification]:
    async with SessionLocal() as s:
        return list((await s.execute(select(Notification).where(Notification.user_id == user_id)
                                      .order_by(Notification.created_at))).scalars())


async def _world(client_factory, db):
    """PAY with a manager (client m) and a member B (client b); one task PAY-1."""
    b_user = await make_user(db, name="Bea")
    m = client_factory()
    _p, manager, _team = await make_project(m, db, "PAY", b_user)
    b = client_factory()
    await login(b, b_user)
    task = (await m.post("/api/projects/PAY/tasks", json={"title": "Fix login", "type": "task"})).json()
    return manager, b_user, m, b, task


async def _notify(user_ids, *, kind=Kind.assigned, task_id=None, project_id=None, actor_id=None, title="T") -> int:
    async with SessionLocal() as s:
        n = await service.notify(s, user_ids, kind, title=title, body="B", link="/x", task_id=task_id,
                                 project_id=project_id, actor_id=actor_id)
        await s.commit()
        return n


async def test_assignment_notifies_assignee_not_actor(client_factory, db):
    manager, bea, m, b, task = await _world(client_factory, db)
    r = await m.patch(f"/api/tasks/{task['key']}", json={"assignee_user_id": str(bea.id)})
    assert r.status_code == 200, r.text
    [n] = await _rows(bea.id)
    assert (n.kind, n.task_id, n.link) == ("assigned", uuid.UUID(task["id"]), f"/projects/PAY/board?task={task['key']}")
    assert task["key"] in n.title and manager.name in n.title and n.body == "Fix login"
    await m.patch(f"/api/tasks/{task['key']}", json={"assignee_user_id": str(manager.id)})
    assert await _rows(manager.id) == []  # the actor assigned themself
    await m.post("/api/projects/PAY/tasks", json={"title": "New", "type": "task", "assignee_user_id": str(bea.id)})
    assert len(await _rows(bea.id)) == 2  # assigned at creation too
    agent = (await b.post("/api/agents", json={"program": "claude_code", "name": "Bea's agent"})).json()
    await b.put(f"/api/agents/{agent['id']}/bindings", json={"bindings": [{"project_ref": "PAY", "local_path": "/r"}]})
    await b.post("/api/notifications/read-all")  # otherwise the unread PAY-1 row holds this one back
    r = await m.patch(f"/api/tasks/{task['key']}", json={"assignee_agent_id": agent["id"]})
    assert r.status_code == 200, r.text
    last = (await _rows(bea.id))[-1]
    assert last.kind == "assigned" and "Bea's agent" in last.title  # the agent's owner hears about it


async def test_dedupe_and_no_self_notify(client_factory, db):
    manager, bea, _m, _b, task = await _world(client_factory, db)
    tid = uuid.UUID(task["id"])
    assert await _notify([bea.id, manager.id], task_id=tid, actor_id=manager.id) == 1
    assert await _notify([bea.id], task_id=tid) == 0  # same user, kind and task, unread, within 10 minutes
    assert await _notify([bea.id], task_id=tid, kind=Kind.mentioned) == 1  # another kind
    async with SessionLocal() as s:
        await s.execute(update(Notification).values(created_at=datetime.now(UTC) - timedelta(minutes=11)))
        await s.commit()
    assert await _notify([bea.id], task_id=tid) == 1
    rows = await _rows(bea.id)
    async with SessionLocal() as s:
        await s.execute(update(Notification).where(Notification.user_id == bea.id).values(read_at=datetime.now(UTC)))
        await s.commit()
    assert await _notify([bea.id], task_id=tid) == 1  # read ones do not hold a new one back
    assert len(rows) == 3


async def test_recipients_filtered_by_access_and_status(client_factory, db):
    _manager, bea, _m, _b, task = await _world(client_factory, db)
    tid = uuid.UUID(task["id"])
    outsider = await make_user(db)
    gone = await make_user(db)
    await db.execute(update(User).where(User.id == gone.id).values(status=UserStatus.deactivated))
    viewer = await make_user(db, role=Role.viewer)
    db.add(TeamMember(team_id=(await db.execute(select(TeamMember.team_id).where(TeamMember.user_id == bea.id))
                               ).scalar_one(), user_id=viewer.id))
    await db.commit()
    admin = await make_user(db, role=Role.admin)
    assert await _notify([outsider.id, gone.id, bea.id, admin.id, uuid.uuid4()], task_id=tid) == 2
    assert await _rows(outsider.id) == [] and await _rows(gone.id) == []
    async with SessionLocal() as s:
        assert await service.readable_by(s, await s.get(User, outsider.id), task_id=tid) is False
        assert await service.readable_by(s, await s.get(User, viewer.id), task_id=tid) is True
    project_id = uuid.UUID(task["project_id"])
    # a viewer reads the project but cannot answer a question, so is not told one is waiting
    assert await _notify([viewer.id, bea.id], kind=Kind.question_waiting, project_id=project_id) == 1
    assert await _rows(viewer.id) == []
    assert await _notify([viewer.id], kind=Kind.mentioned, task_id=tid) == 1


async def test_preferences_default_and_update(client_factory, db):
    _manager, bea, m, b, task = await _world(client_factory, db)
    prefs = (await b.get("/api/me/notification-preferences")).json()
    assert prefs == [{"kind": k.value, "in_app": True, "email": k != Kind.question_waiting} for k in Kind]
    r = await b.put("/api/me/notification-preferences",
                    json=[{"kind": "assigned", "in_app": False, "email": False}])
    assert r.status_code == 200
    assert next(p for p in r.json() if p["kind"] == "assigned") == {"kind": "assigned", "in_app": False, "email": False}
    await m.patch(f"/api/tasks/{task['key']}", json={"assignee_user_id": str(bea.id)})
    assert await _rows(bea.id) == []
    assert (await b.put("/api/me/notification-preferences", json=[{"kind": "nope", "in_app": True, "email": True}])
            ).status_code == 422
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "notification.preferences_changed"))).scalars().all()


async def _smtp(db):
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    if org is None:
        db.add(OrgSettings(id=ORG_SETTINGS_ID, name="Acme", smtp_host="smtp.example.com"))
    else:
        org.smtp_host = "smtp.example.com"
    await db.commit()


async def _email_jobs() -> list[Job]:
    async with SessionLocal() as s:
        return list((await s.execute(select(Job).where(Job.kind == "notify.email"))).scalars())


async def test_email_job_sends_via_outbox_and_survives_failure(client_factory, db, monkeypatch):
    _manager, bea, _m, _b, task = await _world(client_factory, db)
    tid = uuid.UUID(task["id"])
    await _notify([bea.id], task_id=tid, title="PAY-1 is yours")
    assert await _email_jobs() == []  # no SMTP: nothing queued, the in-app row still exists
    assert len(await _rows(bea.id)) == 1
    await _smtp(db)
    await _notify([bea.id], task_id=tid, kind=Kind.mentioned, title="Mentioned on PAY-1")
    [job] = await _email_jobs()
    outbox = OutboxMailer()

    async def mailer(_db):
        return outbox

    monkeypatch.setattr(notify_jobs, "get_mailer", mailer)
    async with SessionLocal() as s:
        await notify_jobs.send_email(s, job.payload)
    [(to, subject, body)] = outbox.sent
    assert to == bea.email and subject == "[MegooColab] Mentioned on PAY-1"
    assert body == f"B\n\n{get_settings().public_url}/x"

    class Broken:
        async def send(self, *a):
            raise OSError("smtp down")

    async def broken(_db):
        return Broken()

    monkeypatch.setattr(notify_jobs, "get_mailer", broken)
    async with SessionLocal() as s:
        with pytest.raises(OSError):
            await notify_jobs.send_email(s, job.payload)  # the job fails and is retried by the queue
    assert len(await _rows(bea.id)) == 2  # the notification stands


async def test_list_read_and_unread_count(client_factory, db):
    _manager, bea, _m, b, task = await _world(client_factory, db)
    async with SessionLocal() as s:
        base = datetime.now(UTC) - timedelta(hours=2)
        for i in range(55):
            s.add(Notification(user_id=bea.id, kind="assigned", title=f"n{i}", body="", link="/x",
                               created_at=base + timedelta(minutes=i)))
        await s.commit()
    page = (await b.get("/api/notifications")).json()
    assert len(page) == 50 and page[0]["title"] == "n54" and page[-1]["title"] == "n5"
    rest = (await b.get("/api/notifications", params={"before": page[-1]["created_at"], "before_id": page[-1]["id"]})).json()
    assert [n["title"] for n in rest] == ["n4", "n3", "n2", "n1", "n0"]
    assert (await b.get("/api/notifications/unread-count")).json() == {"count": 55}
    assert (await b.post(f"/api/notifications/{page[0]['id']}/read")).status_code == 204
    assert (await b.get("/api/notifications/unread-count")).json() == {"count": 54}
    assert len((await b.get("/api/notifications", params={"unread": "true"})).json()) == 50
    other = client_factory()
    await login(other, await make_user(db))
    assert (await other.post(f"/api/notifications/{page[1]['id']}/read")).status_code == 404
    assert (await b.post("/api/notifications/read-all")).status_code == 204
    assert (await b.get("/api/notifications/unread-count")).json() == {"count": 0}
    assert task


async def test_live_event_per_user(client_factory, db, monkeypatch):
    _manager, bea, _m, _b, task = await _world(client_factory, db)
    seen = []
    real = service.publish

    async def capture(session, event):
        seen.append(event)
        await real(session, event)

    monkeypatch.setattr(service, "publish", capture)
    await _notify([bea.id], task_id=uuid.UUID(task["id"]))
    assert [(e.type, e.user_id) for e in seen] == [("notification.created", bea.id)]
