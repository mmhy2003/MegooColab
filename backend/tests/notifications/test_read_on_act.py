"""Acting on what a notification is about marks it read: a person's unread notifications about a task (or a question)
are read once they do something on it. Looking does not count, nor what others or the system do."""

import uuid

from app.core.db import SessionLocal
from app.notifications.models import Kind
from app.tasks import service as task_service
from app.tasks.models import Task
from app.workflow.models import DocKind
from tests.a2a.test_answer import _draft
from tests.a2a.test_ask import _ask
from tests.a2a.test_ask import _world as _qworld
from tests.chats.helpers import start, world
from tests.chats.test_chat_workflow import _round, _waiting_for
from tests.notifications.test_core import _notify, _rows, _world


async def _unread(user_id) -> list[str]:
    return [n.title for n in await _rows(user_id) if n.read_at is None]


async def test_commenting_reads_your_notifications_about_that_task(client_factory, db):
    manager, bea, m, b, task = await _world(client_factory, db)
    other = (await m.post("/api/projects/PAY/tasks", json={"title": "Other", "type": "task"})).json()
    await _notify([bea.id], kind=Kind.needs_you, task_id=uuid.UUID(task["id"]), title="about PAY-1")
    await _notify([bea.id], kind=Kind.mentioned, task_id=uuid.UUID(task["id"]), title="mention on PAY-1")
    await _notify([bea.id], kind=Kind.assigned, task_id=uuid.UUID(other["id"]), title="about PAY-2")
    await _notify([manager.id], kind=Kind.needs_you, task_id=uuid.UUID(task["id"]), title="manager's")

    assert (await b.get(f"/api/tasks/{task['key']}")).status_code == 200
    assert len(await _unread(bea.id)) == 3  # looking is not acting

    r = await b.post(f"/api/tasks/{task['key']}/comments", json={"body_md": "On it"})
    assert r.status_code == 201, r.text
    assert await _unread(bea.id) == ["about PAY-2"]
    assert await _unread(manager.id) == ["manager's"]  # someone else's stay


async def test_changing_a_task_reads_your_notifications_about_it(client_factory, db):
    manager, _bea, m, _b, task = await _world(client_factory, db)
    await _notify([manager.id], kind=Kind.needs_you, task_id=uuid.UUID(task["id"]), title="about PAY-1")
    r = await m.patch(f"/api/tasks/{task['key']}", json={"title": "Fix the login"})
    assert r.status_code == 200, r.text
    assert await _unread(manager.id) == []


async def test_what_the_system_records_reads_nothing(client_factory, db):
    manager, _bea, _m, _b, task = await _world(client_factory, db)
    await _notify([manager.id], kind=Kind.needs_you, task_id=uuid.UUID(task["id"]), title="about PAY-1")
    async with SessionLocal() as s:
        t = await s.get(Task, uuid.UUID(task["id"]))
        await task_service.record_event(s, t, None, "workflow.no_column", {})
        await s.commit()
    assert await _unread(manager.id) == ["about PAY-1"]


async def test_a_notification_made_while_you_act_stays_unread(client_factory, db):
    manager, _bea, _m, _b, task = await _world(client_factory, db)
    async with SessionLocal() as s:
        t = await s.get(Task, uuid.UUID(task["id"]))
        await task_service.record_event(s, t, manager.id, "field_changed", {"field": "title"})
        from app.notifications import service

        await service.notify(s, [manager.id], Kind.needs_you, title="new, from this very change", body="B",
                             link="/x", task_id=t.id)
        await task_service.record_event(s, t, manager.id, "field_changed", {"field": "labels"})
        await s.commit()
    assert await _unread(manager.id) == ["new, from this very change"]


async def test_approving_a_draft_answer_reads_its_notification(client_factory, db):
    _asker, target_member, _outsider, a, b, _c = await _qworld(client_factory, db)
    q = (await _ask(a)).json()["question"]
    await _draft(db, target_member, q["id"])
    assert len(await _unread(target_member.id)) == 1
    r = await b.post(f"/api/questions/{q['id']}/approve", json={})
    assert r.status_code == 200, r.text
    assert await _unread(target_member.id) == []


async def test_replying_in_a_chat_reads_what_its_round_told_you(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await _waiting_for(db, rnd, DocKind.plan, steps=[{"title": "One", "detail": "d"}])
    me = (await client.get("/api/auth/me")).json()["user"]["id"]
    await _notify([uuid.UUID(me)], kind=Kind.needs_you, task_id=rnd.id, title="the plan waits")
    assert await _unread(uuid.UUID(me)) == ["the plan waits"]
    r = await client.post(f"/api/chats/{chat['id']}/messages", json={"body": "Split it in two"})
    assert r.status_code == 201, r.text
    assert await _unread(uuid.UUID(me)) == []
