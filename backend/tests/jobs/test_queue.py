import asyncio
from datetime import timedelta

from sqlalchemy import func, select, update

from app.auth.models import Role
from app.core.db import SessionLocal
from app.jobs import queue
from app.jobs.models import Job, JobStatus
from app.jobs.worker import run_worker
from tests.factories import login, make_user


async def test_enqueue_dedupes_while_queued(db):
    first = await queue.enqueue(db, "t.x", {"n": 1}, dedupe_key="k1")
    await db.commit()
    assert first is not None
    assert await queue.enqueue(db, "t.x", {"n": 2}, dedupe_key="k1") is None
    await db.commit()
    other = await queue.enqueue(db, "t.x", {"n": 3}, dedupe_key="k2")
    await db.commit()
    assert other is not None and other.id != first.id
    # no dedupe key: never deduped
    assert await queue.enqueue(db, "t.x", {}) is not None
    assert await queue.enqueue(db, "t.x", {}) is not None


async def test_enqueue_allowed_again_once_running(db):
    await queue.enqueue(db, "t.x", {}, dedupe_key="k1")
    await db.commit()
    job = await queue.claim(db, {"t.x"})
    await db.commit()
    assert job is not None and job.status == JobStatus.running
    # an update made while the job runs must not be dropped
    assert await queue.enqueue(db, "t.x", {}, dedupe_key="k1") is not None


async def test_claim_skips_locked_rows_two_workers(db):
    await queue.enqueue(db, "t.x", {"n": 1})
    await queue.enqueue(db, "t.x", {"n": 2})
    await db.commit()
    async with SessionLocal() as a, SessionLocal() as b:
        ja = await queue.claim(a, {"t.x"})
        jb = await queue.claim(b, {"t.x"})
        assert ja is not None and jb is not None and ja.id != jb.id
        assert await queue.claim(b, {"t.x"}) is None
        await a.commit()
        await b.commit()


async def test_claim_ignores_unknown_kinds_and_future_jobs(db):
    await queue.enqueue(db, "t.other", {})
    await queue.enqueue(db, "t.x", {}, run_after=func.now() + timedelta(hours=1))
    await db.commit()
    assert await queue.claim(db, {"t.x"}) is None


async def test_failed_job_backs_off_then_fails_after_max_attempts(db):
    job = await queue.enqueue(db, "t.x", {})
    job.max_attempts = 2
    await db.commit()

    job = await queue.claim(db, {"t.x"})
    await queue.fail(db, job, "boom " * 200)
    await db.commit()
    await db.refresh(job)
    assert job.status == JobStatus.queued and job.attempts == 1
    assert len(job.last_error) == 500
    backoff = (await db.execute(select(func.extract("epoch", Job.run_after - func.now())).where(Job.id == job.id))).scalar_one()
    assert 15 < backoff <= 20  # 2^1 * 10 s
    assert await queue.claim(db, {"t.x"}) is None  # backing off

    await db.execute(update(Job).where(Job.id == job.id).values(run_after=func.now() - timedelta(seconds=1)))
    await db.commit()
    job = await queue.claim(db, {"t.x"})
    assert job.attempts == 2
    await queue.fail(db, job, "boom again")
    await db.commit()
    await db.refresh(job)
    assert job.status == JobStatus.failed and job.finished_at is not None
    assert job.last_error == "boom again"


def test_backoff_is_capped_at_one_hour():
    assert queue.backoff(1) == timedelta(seconds=20)
    assert queue.backoff(3) == timedelta(seconds=80)
    assert queue.backoff(20) == timedelta(hours=1)


async def test_expired_lease_is_reclaimed(db):
    await queue.enqueue(db, "t.x", {})
    await db.commit()
    job = await queue.claim(db, {"t.x"})
    await db.commit()
    async with SessionLocal() as other:
        assert await queue.claim(other, {"t.x"}) is None  # lease still held
        await other.commit()
    await db.execute(update(Job).where(Job.id == job.id).values(locked_until=func.now() - timedelta(seconds=1)))
    await db.commit()
    async with SessionLocal() as other:
        again = await queue.claim(other, {"t.x"})
        assert again is not None and again.id == job.id and again.attempts == 2
        await other.commit()


async def test_expired_lease_past_max_attempts_fails(db):
    job = await queue.enqueue(db, "t.x", {})
    job.max_attempts = 1
    await db.commit()
    job = await queue.claim(db, {"t.x"})
    await db.commit()
    await db.execute(update(Job).where(Job.id == job.id).values(locked_until=func.now() - timedelta(seconds=1)))
    await db.commit()
    assert await queue.claim(db, {"t.x"}) is None
    await db.commit()
    await db.refresh(job)
    assert job.status == JobStatus.failed and job.last_error == "lease_expired"


async def _run_until(predicate, timeout=10.0):
    stop = asyncio.Event()
    task = asyncio.create_task(run_worker(stop, poll_seconds=0.2))
    try:
        async with asyncio.timeout(timeout):
            while not await predicate():
                await asyncio.sleep(0.05)
    finally:
        stop.set()
        await asyncio.wait_for(task, 5)


async def _status(job_id):
    async with SessionLocal() as s:
        return (await s.get(Job, job_id)).status


async def test_worker_runs_registered_handler_and_completes(db, monkeypatch):
    seen = []

    async def handler(session, payload):
        seen.append(payload)

    monkeypatch.setitem(queue.HANDLERS, "t.ok", handler)
    job = await queue.enqueue(db, "t.ok", {"n": 7})
    await db.commit()

    async def done():
        return await _status(job.id) == JobStatus.done

    await _run_until(done)
    assert seen == [{"n": 7}]


async def test_handler_exception_records_last_error(db, monkeypatch):
    async def handler(session, payload):
        raise ValueError("bad input")

    monkeypatch.setitem(queue.HANDLERS, "t.bad", handler)
    job = await queue.enqueue(db, "t.bad", {})
    await db.commit()

    async def errored():
        async with SessionLocal() as s:
            row = await s.get(Job, job.id)
            return row.last_error is not None

    await _run_until(errored)
    async with SessionLocal() as s:
        row = await s.get(Job, job.id)
    assert row.status == JobStatus.queued and row.attempts == 1
    assert row.last_error == "ValueError: bad input"


async def test_handler_writes_roll_back_on_failure(db, monkeypatch):
    async def handler(session, payload):
        await queue.enqueue(session, "t.side", {})
        raise RuntimeError("after write")

    monkeypatch.setitem(queue.HANDLERS, "t.bad", handler)
    job = await queue.enqueue(db, "t.bad", {})
    await db.commit()

    async def errored():
        async with SessionLocal() as s:
            return (await s.get(Job, job.id)).last_error is not None

    await _run_until(errored)
    async with SessionLocal() as s:
        kinds = (await s.execute(Job.__table__.select())).all()
    assert [r.kind for r in kinds] == ["t.bad"]


async def test_admin_jobs_list_admin_only(client, db):
    j = await queue.enqueue(db, "t.x", {})
    await db.commit()
    member = await make_user(db)
    await login(client, member)
    assert (await client.get("/api/admin/jobs")).status_code == 403
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    r = await client.get("/api/admin/jobs")
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [str(j.id)]
    assert set(r.json()[0]) == {"id", "kind", "status", "attempts", "last_error", "created_at", "finished_at"}
    assert (await client.get("/api/admin/jobs", params={"status": "failed"})).json() == []


def test_worker_entry_point_loads_kb_handlers():
    import importlib

    from app import worker as entry

    for name in entry.HANDLER_MODULES:
        importlib.import_module(name)
    assert {"kb.embed", "kb.reembed_all"} <= set(queue.HANDLERS)
