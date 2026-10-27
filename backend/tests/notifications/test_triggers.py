"""What sends notifications (NOT-1): a workflow waiting on a human, mentions, an agent dropping mid-task, and
agent-to-agent questions that need a person."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.a2a import routing
from app.a2a.models import Question
from app.auth.models import Role
from app.core.db import SessionLocal
from app.notifications import jobs as notify_jobs
from app.notifications.models import Notification
from app.notifications.service import mentioned_user_ids
from app.tasks.models import Task
from app.teams.models import TeamMember
from app.workflow import engine
from app.workflow.models import Needs
from tests.a2a.test_answer import _draft
from tests.a2a.test_ask import _ask, _world
from tests.agent_runs.test_run_guards import _next_of
from tests.factories import make_user
from tests.notifications.test_core import _rows
from tests.runner.test_runner_ws import URL, _login
from tests.workflow.test_engine import _ask as _wf_ask
from tests.workflow.test_engine import (
    _board,
    _finish,
    _hello_v2,
    _member,
    _move,
    _runs,
    _started,
    _until,
)


async def _read_all(user_id) -> None:
    async with SessionLocal() as s:
        await s.execute(update(Notification).where(Notification.user_id == user_id)
                        .values(read_at=datetime.now(UTC)))
        await s.commit()


async def _wait(task_id, need: Needs) -> None:
    async with SessionLocal() as s:
        wf = await engine.lock_workflow(s, task_id)
        if need == Needs.escalation:
            await engine.escalate(s, wf, "retries_exhausted")
        else:
            await engine.wait_for(s, wf, need)
        await s.commit()


async def test_needs_you_for_each_wait(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _wf_ask(b.task_id, run.id)
    await _finish(b.manager.id, run, "completed")  # the agent asked: the workflow waits on its owner
    [n] = await _rows(b.manager.id)
    assert (n.kind, n.task_id, n.link) == ("needs_you", b.task_id, f"/projects/PAY/board?task={b.key}")
    assert b.key in n.title and "question" in n.title and n.body == "Fix login"
    await _wait(b.task_id, Needs.question)
    assert len(await _rows(b.manager.id)) == 1  # a second wait within 10 minutes: no repeat
    member = await _member(db, tc)  # the human assignee hears too (connect_only: a person drives the agent)
    await db.execute(update(Task).where(Task.id == b.task_id).values(assignee_user_id=member.id,
                                                                      assignee_agent_id=None))
    await db.commit()
    words = {Needs.design_approval: "design", Needs.plan_approval: "plan", Needs.escalation: "retries_exhausted",
             Needs.human_code_review: "review"}
    for need, word in words.items():
        await _read_all(b.manager.id)
        await _read_all(member.id)
        await _wait(b.task_id, need)
        for user in (b.manager, member):
            last = (await _rows(user.id))[-1]
            assert last.kind == "needs_you" and word in last.title and last.read_at is None, (need, last.title)


async def test_mention_notifies_readable_users(client_factory, db):
    from tests.notifications.test_core import _world as _pay

    manager, bea, m, _b, task = await _pay(client_factory, db)
    body = f"Can you look, @[Bea](user:{bea.id})? Also @[Bea](user:{bea.id}) and @[Me](user:{manager.id})"
    r = await m.post(f"/api/tasks/{task['key']}/comments", json={"body_md": body})
    assert r.status_code == 201, r.text
    [n] = await _rows(bea.id)
    assert (n.kind, n.task_id) == ("mentioned", uuid.UUID(task["id"]))
    assert manager.name in n.title and task["key"] in n.title
    assert n.body.startswith("Can you look, @Bea?") and "user:" not in n.body
    assert await _rows(manager.id) == []  # mentioning yourself does nothing


def test_mentioned_user_ids_parsing():
    a, b = uuid.uuid4(), uuid.uuid4()
    text = f"@[A](user:{a}) @[B](user:{b}) @[A again](user:{a}) [x](user:{uuid.uuid4()}) @[bad](user:nope)"
    assert mentioned_user_ids(text) == [a, b]  # in order, once each; only the @[..](user:..) token counts
    many = " ".join(f"@[U{i}](user:{uuid.uuid4()})" for i in range(25))
    assert len(mentioned_user_ids(many)) == 20
    assert mentioned_user_ids(f"@[{'n' * 201}](user:{a})") == []


async def test_mention_of_outsider_ignored(client_factory, db):
    from tests.notifications.test_core import _world as _pay

    _manager, _bea, m, _b, task = await _pay(client_factory, db)
    outsider = await make_user(db)
    r = await m.post(f"/api/tasks/{task['key']}/comments",
                     json={"body_md": f"ping @[Out](user:{outsider.id}) @[Ghost](user:{uuid.uuid4()})"})
    assert r.status_code == 201
    assert await _rows(outsider.id) == []
    assert (await db.execute(select(Notification))).scalars().all() == []


async def test_agent_offline_mid_task(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    watcher = await _member(db, tc)
    _login(tc, watcher)
    assert tc.put(f"/api/tasks/{b.key}/watch").status_code == 204
    _login(tc, b.manager)
    assert _move(tc, b.key, b.cols["working"]).status_code == 200
    with tc.websocket_connect(URL, headers=b.token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello_v2(b.agent))
        _next_of(ws, "run_start")
    # the runner dropped mid-run

    async def failed():
        return next(r.status for r in await _runs(b.task_id)) == "failed"

    await _until(failed, "the dropped run to fail")
    for user in (b.manager, watcher):  # the requester (also a watcher, told once) and the other watcher
        [n] = [x for x in await _rows(user.id) if x.kind == "agent_offline"]
        assert b.key in n.title and n.link == f"/projects/PAY/board?task={b.key}"


async def test_a2a_draft_and_needs_human(client_factory, db):
    asker, target_member, _outsider, a, _b, _c = await _world(client_factory, db)
    q = (await _ask(a)).json()["question"]
    await _draft(db, target_member, q["id"])  # a manual-mode agent drafted an answer: its owner approves
    [n] = await _rows(target_member.id)
    assert (n.kind, n.link) == ("needs_you", f"/questions/{q['id']}") and "QBB-Q1" in n.title
    assert await _rows(asker.id) == []
    q2 = (await _ask(a, body="Second question?")).json()["question"]
    viewer = await make_user(db, role=Role.viewer)
    team_id = (await db.execute(select(TeamMember.team_id).where(TeamMember.user_id == target_member.id))).scalar_one()
    db.add(TeamMember(team_id=team_id, user_id=viewer.id))
    await db.execute(update(Question).where(Question.id == uuid.UUID(q2["id"]))
                     .values(tried_agent_ids=[str(uuid.uuid4())]))
    await db.commit()
    async with SessionLocal() as s:
        await routing.route_question(s, uuid.UUID(q2["id"]))  # every agent tried: a person has to answer
        await s.commit()
    waiting = [x for x in await _rows(target_member.id) if x.kind == "question_waiting"]
    assert [x.link for x in waiting] == [f"/questions/{q2['id']}"] and "QBB-Q2" in waiting[0].title
    assert await _rows(viewer.id) == [] and await _rows(asker.id) == []


async def test_question_waiting_once(client_factory, db):
    _asker, target_member, _outsider, a, _b, _c = await _world(client_factory, db)
    q = (await _ask(a)).json()["question"]
    qid = uuid.UUID(q["id"])

    async def tick():
        async with SessionLocal() as s:
            await notify_jobs.questions_waiting(s, {})
            await s.commit()

    await tick()
    assert await _rows(target_member.id) == []  # queued for less than 15 minutes
    await db.execute(update(Question).where(Question.id == qid)
                     .values(created_at=datetime.now(UTC) - timedelta(minutes=16)))
    await db.commit()
    await tick()
    [n] = await _rows(target_member.id)
    assert (n.kind, n.link) == ("question_waiting", f"/questions/{q['id']}")
    assert (await db.get(Question, qid, populate_existing=True)).waiting_notified_at is not None
    await _read_all(target_member.id)
    await tick()
    await tick()
    assert len(await _rows(target_member.id)) == 1
