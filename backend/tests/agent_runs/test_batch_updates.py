"""Run updates that arrive together are stored in one transaction, one task.updated per task (MC-214)."""

import uuid

from sqlalchemy import update

import app.agent_runs.service as service
import app.runner.router as rr
from app.agent_runs.models import AgentRun
from app.agent_runs.service import apply_updates
from app.agents.models import Agent
from app.runner.protocol import RunUpdate
from app.runner.registry import RunnerConn, registry
from tests.agent_runs.test_dispatch import _FakeSocket, _fake_conn
from tests.agent_runs.test_updates import _events, _row, _running
from tests.factories import make_user


def _update(run_id, seq: int, text: str) -> RunUpdate:
    return RunUpdate(type="run_update", run_id=run_id, seq=seq, kind="message", data={"text": text})


def _record_publish(monkeypatch) -> list:
    published = []
    original = service.publish

    async def _publish(db, event):
        published.append(event)
        return await original(db, event)

    monkeypatch.setattr(service, "publish", _publish)
    return published


async def test_a_batch_is_one_transaction_with_one_task_updated_per_task(client, db, monkeypatch):
    me, _agent, [a, b] = await _running(client, db, n=2)
    published = _record_publish(monkeypatch)
    batch = [_update(a, 1, "a1"), _update(b, 1, "b1"), _update(a, 2, "a2"), _update(b, 2, "b2"), _update(a, 3, "a3")]
    await apply_updates(db, me.id, batch)
    await db.commit()
    events = await _events(db)
    assert [e.data["text"] for e in events] == ["a1", "b1", "a2", "b2", "a3"]
    times = [e.created_at for e in events]
    assert all(x < y for x, y in zip(times, times[1:], strict=False)), times
    updated = [e.task_id for e in published if e.type == "task.updated"]
    tasks = {(await _row(db, a)).task_id, (await _row(db, b)).task_id}
    assert sorted(updated, key=str) == sorted(tasks, key=str)
    assert (await _row(db, a)).last_seq == 3 and (await _row(db, b)).last_seq == 2


async def test_a_batch_keeps_the_checks_per_update(client, db):
    me, _agent, [run_id, strangers] = await _running(client, db, n=2)
    stranger = await make_user(db)
    theirs = Agent(owner_id=stranger.id, name="theirs", program="claude_code")
    db.add(theirs)
    await db.flush()
    await db.execute(update(AgentRun).where(AgentRun.id == strangers).values(agent_id=theirs.id))
    await db.commit()
    batch = [
        _update(run_id, 2, "one"), _update(run_id, 2, "again"), _update(run_id, 1, "older"),
        _update(strangers, 1, "not mine"), _update(run_id, 3, "two"),
    ]
    await apply_updates(db, me.id, batch)
    await db.commit()
    assert [e.data["text"] for e in await _events(db)] == ["one", "two"]
    assert (await _row(db, run_id)).last_seq == 3
    assert (await _row(db, strangers)).last_seq == 0


async def test_a_failing_batch_falls_back_to_one_by_one(client, db, monkeypatch, caplog):
    me, agent, [run_id] = await _running(client, db)
    conn = await _fake_conn(me, agent, _FakeSocket())

    async def _broken(db, conn_user_id, updates):
        raise RuntimeError("boom")

    monkeypatch.setattr(rr, "apply_updates", _broken)
    try:
        await rr._run_updates(conn, [_update(run_id, 1, "one"), _update(run_id, 2, "two")])
    finally:
        registry._conns.pop(me.id, None)
    assert [e.data["text"] for e in await _events(db)] == ["one", "two"]
    assert "applying them one by one" in caplog.text


async def test_updates_from_another_machine_are_ignored(client, db):
    me, agent, [run_id] = await _running(client, db)
    await _fake_conn(me, agent, _FakeSocket())
    other = RunnerConn(uuid.uuid4(), me.id, _FakeSocket())  # another token of the same person
    try:
        await rr._run_updates(other, [_update(run_id, 1, "one")])
    finally:
        registry._conns.pop(me.id, None)
    assert await _events(db) == []
    assert (await _row(db, run_id)).last_seq == 0


async def test_a_batch_of_a_stranger_stores_nothing(client, db):
    _me, _agent, [run_id] = await _running(client, db)
    stranger = await make_user(db)
    await apply_updates(db, stranger.id, [_update(run_id, 1, "hi")])
    await db.commit()
    assert await _events(db) == []
