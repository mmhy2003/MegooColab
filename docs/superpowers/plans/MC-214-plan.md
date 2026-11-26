# MC-214 plan: the runner socket survives load, and runs survive a short disconnect

## Goal

Two runs on one runner no longer drop its socket. When the socket does drop, the runs keep going for a grace period and are picked up again when the runner reconnects.

## Architecture

**Backend.**
- A new `app/runner/inbox.py` gives each connection a reader task and a worker task. The reader is the only caller of `ws.receive()`. It calls `touch()`, validates each frame and queues it. The worker applies the messages in order and takes consecutive `run_update`s as one batch (`apply_updates`, one transaction, one `task.updated` per task).
- When a connection ends, the run messages still queued are applied first.
- A new `app/runner/grace.py` keeps one deadline per runner token. A dropped `resume/1` connection sets a deadline instead of failing its runs. A `runs_held` message claims runs, cancels runs that are no longer running and fails runs it did not list. A deadline that passes fails the runs as a disconnect does today. Startup gives every token that has running runs a deadline.
- The DB pool becomes configurable (20/20). AI usage rows are written by background tasks.

**Runner.**
- The manager remembers `welcome.grace_seconds`. On a disconnect with a grace period it keeps its runs and starts a timer.
- Run messages that cannot be sent go to an outbox.
- On the next connection's welcome the manager sends `runs_held`, then the outbox.
- `conn.Client.ReconnectCap` caps the reconnect delay at 5 s while runs are held.
- A `run_start` for a task that still has a live run of the same agent cancels and silences the old run.

## Conventions for every step

- Work on branch `megoo/MC-214-parallel-runs-on-one-runner-drop-its-con`. Make one commit per step. Subject: `type(area): plain sentence (MC-214)`. The body says why. End the message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/`.
- TDD: write the test, run it, see it fail for the stated reason, implement, then run it again and see it pass.
- **BT `<paths>`** (from `backend/`): `megoocolab-runner services run test -- uv run pytest <paths> -q`. Never run two pytest commands at once.
- **LINT** (from `backend/`): `uvx ruff check --select E9,F <changed .py files>`.
- **GO `<pkg>` `<regex>`** (from `runner/`): `go test ./internal/<pkg>/ -run '<regex>' -count=1`. Before committing a Go step, also run `go vet ./... && go test ./...`.
- Backend tests are packages (`backend/tests/**/__init__.py`). Import helpers as `from tests.agent_runs.test_dispatch import _setup`.
- Known flake: `TestSteerAfterTurnEndsReportsNotRunningAndCancelsStrayTurn`. If it passes on a rerun, it is not your failure.

## File map

| File | Change |
|---|---|
| `backend/app/core/config.py` | `db_pool_size=20`, `db_max_overflow=20` (step 1), `runner_grace_seconds=60` (step 6) |
| `backend/app/core/db.py` | `engine_options(settings)`, used by `create_async_engine` |
| `backend/Dockerfile` | uvicorn `--ws-ping-timeout 60` |
| `deploy/docker-compose.yml` | backend `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `RUNNER_GRACE_SECONDS`; worker 5/10 |
| `docs/install.md` | rows for the three settings |
| `backend/app/ai/client.py` | `_record` runs as a background task; `usage_written()` |
| `backend/app/main.py`, `backend/app/worker.py`, `backend/app/cli.py` | await `usage_written()` at the end; main also starts and cancels the grace deadlines |
| `backend/tests/conftest.py` | `await usage_written()` before truncating |
| `backend/app/runner/inbox.py` (new) | `Inbox`, `End`, `INBOX_MAX`, `BATCH_WINDOW_SECONDS`, `BATCH_MAX`, `RUN_MESSAGES` |
| `backend/app/runner/router.py` | `_apply`, `_handle` wrapper, `_run_updates`, `_serve` on the inbox, `_cleanup(conn, inbox)`, hello / `runs_held` / grace wiring |
| `backend/app/agent_runs/service.py` | `_store_update`, `apply_updates`, `_end_disconnected_run`, `fail_held_runs`, `claim_held_runs`, `running_runs_by_token`; `fail_disconnected_runs` skips held runs |
| `backend/app/runner/protocol.py` | `Welcome.grace_seconds`, `RunsHeld` |
| `backend/app/runner/registry.py` | `RESUME_CAPABILITY`, `RunnerConn.runs_held_seen` |
| `backend/app/runner/grace.py` (new) | `seconds()`, `MARGIN_SECONDS`, `hold`, `pending`, `cancel`, `cancel_all`, `expire`, `hold_at_startup` |
| `backend/tests/runner/live.py` (new) | `live_server()` (real uvicorn), `running_runs()` set-up |
| new backend tests | `tests/core/test_db_pool.py`, `tests/ai/test_usage_background.py`, `tests/runner/test_inbox.py`, `tests/runner/test_inbox_unit.py`, `tests/agent_runs/test_batch_updates.py`, `tests/runner/test_resume_protocol.py`, `tests/agent_runs/test_held_runs.py`, `tests/runner/test_grace.py`, `tests/runner/test_grace_startup.py` |
| `runner/internal/protocol/protocol.go` | `TypeRunsHeld`, `CapabilityResume`, `RunsHeld`, `NewRunsHeld`, `RunsHeldLimit`, `Welcome.GraceSeconds`; `resume/1` added to the hello in step 13 |
| `runner/internal/conn/conn.go` | `Client.ReconnectCap` |
| `runner/internal/jobs/outbox.go` (new) | `outbox` |
| `runner/internal/jobs/grace.go` (new) | `disconnected`, `graceExpired`, `resume`, `ReconnectCap`, `heldRuns` |
| `runner/internal/jobs/manager.go`, `steer.go` | `sendRun`, grace fields, Serve wiring, `abandoned` runs |
| new Go tests | `internal/jobs/outbox_test.go`, `internal/jobs/grace_test.go`, additions in `protocol_test.go`, `conn_test.go`, `manager_test.go` |

## Shared code

### Code A: `backend/app/runner/inbox.py`

```python
"""A runner connection's messages: read as they arrive, applied in order (MC-214).

The reader is the only caller of ws.receive(): it notes that the runner is alive, validates each frame and queues it,
so the socket keeps being read (and uvicorn keeps answering pings) however slow the database is. The worker applies
the messages one at a time, in order, and takes consecutive run updates as one batch."""

import asyncio
import contextlib
import itertools
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.runner.protocol import RunFinished, RunSteerResult, RunUpdate, runner_message
from app.runner.registry import RunnerConn

log = logging.getLogger(__name__)

# module-level so tests can monkeypatch them small
INBOX_MAX = 2000
BATCH_WINDOW_SECONDS = 0.25
BATCH_MAX = 200
# what a connection that ended still applies (Inbox.drain)
RUN_MESSAGES = (RunUpdate, RunFinished, RunSteerResult)


@dataclass(frozen=True)
class End:
    """The end of the runner's input: it went away, or sent a frame that is not a valid message (invalid)."""

    invalid: bool


def _parse(text: str | None):
    if text is None:
        return End(invalid=True)
    try:
        return runner_message.validate_python(json.loads(text))
    except (ValueError, ValidationError):
        return End(invalid=True)


class Inbox:
    def __init__(self, conn: RunnerConn, handle: Callable[[RunnerConn, object], Awaitable[None]],
                 handle_updates: Callable[[RunnerConn, list[RunUpdate]], Awaitable[None]]) -> None:
        self.conn = conn
        self._handle, self._handle_updates = handle, handle_updates
        self._queue: asyncio.Queue = asyncio.Queue(INBOX_MAX)
        self._taken: list = []  # off the queue, not applied yet: a batch being collected and what ended it
        self._busy = False  # a handler is running
        self._stopping = False
        self.end: End | None = None  # set when the worker reached the end of the input
        self.reader: asyncio.Task | None = None
        self.worker: asyncio.Task | None = None

    def start(self) -> None:
        self.reader = asyncio.create_task(self._read())
        self.worker = asyncio.create_task(self._work())

    async def _read(self) -> None:
        warned = False
        try:
            while True:
                message = await self.conn.socket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                self.conn.touch()
                item = _parse(message.get("text"))
                if self._queue.full() and not warned:
                    warned = True
                    log.warning("runner %s: %d messages wait to be applied; reading pauses", self.conn.token_id,
                                INBOX_MAX)
                await self._queue.put(item)
                if isinstance(item, End):
                    return
        except Exception:  # the socket is gone: starlette raises once it is closed
            pass
        await self._queue.put(End(invalid=False))

    async def _work(self) -> None:
        while not self._stopping:
            if not self._taken:
                self._taken.append(await self._queue.get())
            first = self._taken[0]
            if isinstance(first, End):
                self.end = first
                return
            if isinstance(first, RunUpdate):
                await self._collect()
                n = sum(1 for _ in itertools.takewhile(lambda m: isinstance(m, RunUpdate), self._taken))
                await self._apply(self._handle_updates, self._taken[:n], n)
            else:
                await self._apply(self._handle, first, 1)

    async def _collect(self) -> None:
        """More run updates after the first: until another message is next, BATCH_MAX are taken or the window closes."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + BATCH_WINDOW_SECONDS
        while len(self._taken) < BATCH_MAX and isinstance(self._taken[-1], RunUpdate):
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            try:
                async with asyncio.timeout(remaining):
                    self._taken.append(await self._queue.get())
            except TimeoutError:
                return

    async def _apply(self, handler, arg, n: int) -> None:
        self._busy = True
        try:
            await handler(self.conn, arg)
        except Exception:
            log.exception("runner: handling a message failed")
        finally:
            del self._taken[:n]
            self._busy = False

    async def stop(self) -> None:
        """Stop reading. A message being applied is finished first; what is left waits for drain()."""
        self._stopping = True
        for task in (self.reader,):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        if self.worker is not None:
            if not self._busy:
                self.worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.worker
```

Step 5 adds `drain()` (Code B).

### Code B: `Inbox.drain` (step 5)

```python
    async def drain(self) -> None:
        """After stop(): apply the run messages still waiting, in order, so a run_finished that arrived before the
        connection ended is not lost. Anything else describes a connection that is gone and is dropped."""
        items = list(self._taken)
        self._taken.clear()
        while not self._queue.empty():
            items.append(self._queue.get_nowait())
        items = [m for m in items if isinstance(m, RUN_MESSAGES)]
        i = 0
        while i < len(items):
            if isinstance(items[i], RunUpdate):
                j = i
                while j < len(items) and j - i < BATCH_MAX and isinstance(items[j], RunUpdate):
                    j += 1
                await self._apply(self._handle_updates, items[i:j], 0)
                i = j
            else:
                await self._apply(self._handle, items[i], 0)
                i += 1
```

Pass `n=0` so `_apply` deletes nothing from `_taken`.

### Code C: router changes (step 3)

- `_apply(conn, msg)` is today's `_handle` body after parsing, minus `conn.touch()`. Its `RunUpdate` branch calls `await _run_updates(conn, [msg])`.
- `_handle(conn, text) -> bool` stays as a wrapper, because the Tool Hub tests call it directly: parse (return `False` if invalid), `conn.touch()`, `await _apply(conn, msg)`, return `True`.
- Step 3's `_run_updates(conn, updates)` loops `for u in updates:` through today's single-update path (`_on_this_machine` and then `_run_message(apply_update, …)`). Step 4 replaces it.
- `runner_socket`: after `registry.connect`, create `inbox = Inbox(conn, _apply, _run_updates)` and call `await _serve(conn, queue, raw, inbox)`. In `finally`, call `_cleanup(conn, inbox)` (`inbox` starts as `None` beside `conn`).
- `_serve(conn, queue, raw, inbox=None)`:
  - Use `inbox = inbox or Inbox(conn, _apply, _run_updates)` and call `inbox.start()`.
  - Wait on `{inbox.worker, event, replaced}`. When the worker is done: if `inbox.end` is invalid, call `await conn.close(CLOSE_PROTOCOL_ERROR)`. Return either way.
  - Hub events, the idle check (`conn.last_seen`, now refreshed by the reader), the token re-check and "replaced" stay as they are.
  - In `finally`: `await inbox.stop()`, then `await _cancel(event, replaced)`.
- `_cleanup(conn, inbox=None)` keeps its current body for now.

### Code D: batching (step 4)

In `service.py`:

- `_store_update(db, conn_user_id, run_id, seq, kind, data, created_at=None) -> Task | None` is today's `apply_update` body without the final `task.updated`. It returns the task whose views changed:
  - the event case returns the task, and sets `ev.created_at = created_at` on the `record_event` result when `created_at` is given;
  - the `branch` case returns the task only if `record_start_branch` returned `True`;
  - `model_options` and answering runs return `None`.
- `apply_update(...)` calls `_store_update` and publishes `task.updated` when it gets a task. Behaviour is unchanged.

```python
async def apply_updates(db: AsyncSession, conn_user_id: uuid.UUID, updates: list[RunUpdate]) -> None:
    """apply_update for a batch, in one transaction: the same checks per update (owner, running, newer seq) and one
    task.updated per task. Each event gets its own time, a microsecond apart, so the activity feed keeps the batch's
    order (now() would give them all the transaction's start). Does not commit."""
    start = await db.scalar(select(func.clock_timestamp()))
    changed: dict[uuid.UUID, Task] = {}
    for i, u in enumerate(updates):
        task = await _store_update(db, conn_user_id, u.run_id, u.seq, u.kind, u.data,
                                   created_at=start + timedelta(microseconds=i))
        if task is not None:
            changed[task.id] = task
    for task in changed.values():
        await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
```

Import `RunUpdate` from `app.runner.protocol` and `timedelta` from `datetime`.

In `router.py`:

```python
async def _run_updates(conn: RunnerConn, updates: list[RunUpdate]) -> None:
    """A batch of run updates in one transaction, one task.updated per task; if it fails, one by one as before."""
    allowed: dict[uuid.UUID, bool] = {}
    for u in updates:
        if u.run_id not in allowed:
            allowed[u.run_id] = await _on_this_machine(conn, u.run_id)
    mine = [u for u in updates if allowed[u.run_id]]
    if not mine:
        return
    try:
        async with SessionLocal() as db:
            await apply_updates(db, conn.user_id, mine)
            await db.commit()
    except Exception:
        log.exception("runner: a batch of %d run updates failed; applying them one by one", len(mine))
        for u in mine:
            await _run_message(apply_update, conn.user_id, u.run_id, u.seq, u.kind, u.data)
```

### Code E: `backend/app/runner/grace.py` (`seconds()` and `MARGIN_SECONDS` come in step 6, the rest in step 8)

```python
"""How long a dropped runner's running runs wait for it to come back (MC-214). One deadline per runner token, in this
process. The server waits MARGIN_SECONDS longer than the runner: each side notices a dead network at its own time."""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from app.agent_runs.service import fail_held_runs, running_runs_by_token
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.runner.registry import RESUME_CAPABILITY, registry

log = logging.getLogger(__name__)
MARGIN_SECONDS = 30  # module-level so tests can monkeypatch it


def seconds() -> int:
    """RUNNER_GRACE_SECONDS: how long the runner may hold its runs after a drop; 0 is off."""
    return max(0, get_settings().runner_grace_seconds)


@dataclass
class _Deadline:
    user_id: uuid.UUID
    run_ids: set[uuid.UUID]
    task: asyncio.Task


_deadlines: dict[uuid.UUID, _Deadline] = {}


def pending(token_id: uuid.UUID) -> bool:
    return token_id in _deadlines


def hold(token_id: uuid.UUID, user_id: uuid.UUID, run_ids: set[uuid.UUID], delay: float | None = None) -> None:
    """Start the token's deadline (grace + margin), or add the runs to the one already running: a connection that
    drops before it sent runs_held does not move the deadline."""
    if (d := _deadlines.get(token_id)) is not None:
        d.run_ids |= run_ids
        return
    delay = seconds() + MARGIN_SECONDS if delay is None else delay
    _deadlines[token_id] = _Deadline(user_id, set(run_ids), asyncio.create_task(_expire_after(token_id, delay)))


def cancel(token_id: uuid.UUID) -> None:
    if (d := _deadlines.pop(token_id, None)) is not None:
        d.task.cancel()


def cancel_all() -> None:
    for token_id in list(_deadlines):
        cancel(token_id)


async def _expire_after(token_id: uuid.UUID, delay: float) -> None:
    await asyncio.sleep(delay)
    d = _deadlines.pop(token_id, None)
    if d is None:
        return
    try:
        await expire(token_id, d.user_id, d.run_ids)
    except Exception:
        log.exception("runner grace: failing the runs of a runner that did not come back failed")


async def expire(token_id: uuid.UUID, user_id: uuid.UUID, run_ids: set[uuid.UUID]) -> None:
    """The deadline passed. A live connection of the token that may still send runs_held (no hello yet, or resume/1
    and not sent) settles it instead; otherwise the runs no live connection holds end as on a disconnect."""
    conn = registry.conn_for_token(token_id)
    if conn is not None and not conn.runs_held_seen and (conn.version is None or RESUME_CAPABILITY in conn.capabilities):
        return
    from app.workflow import engine  # local: the engine imports the run service

    async with SessionLocal() as db:
        await fail_held_runs(db, token_id, user_id, run_ids)
        await db.commit()
        await engine.dispatch_queued(db)


async def hold_at_startup() -> None:
    """Every runner token with running runs gets a deadline: its runner may come back after a restart."""
    if seconds() <= 0:
        return
    async with SessionLocal() as db:
        held = await running_runs_by_token(db)
    for (token_id, user_id), run_ids in held.items():
        hold(token_id, user_id, run_ids)
```

### Code F: service functions for the grace period (step 7)

```python
async def _end_disconnected_run(db, run, owner_id, *, unauthorized: bool = False) -> None:
    """A running run whose runner is gone: a requested cancel completes; after a 4401 it is cancelled
    (runner_unauthorized); otherwise it fails with runner_disconnected and the agent_offline notification."""
    # body: the three branches of today's fail_disconnected_runs loop, unchanged


async def fail_held_runs(db: AsyncSession, token_id: uuid.UUID, user_id: uuid.UUID, run_ids: set[uuid.UUID]) -> None:
    """A runner's grace period ran out: its running runs that no live connection holds end as on a disconnect. The
    remembered run ids count even if a revoke unlinked their agents meanwhile."""
    mine = or_(Agent.runner_token_id == token_id, AgentRun.id.in_(run_ids))
    async for run, owner_id in _lock_runs_one_by_one(db, (RunStatus.running,), Agent.owner_id == user_id, mine):
        if registry.conn_for_run(run.id) is not None:
            continue
        await _end_disconnected_run(db, run, owner_id)


async def claim_held_runs(db: AsyncSession, conn: RunnerConn, run_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """runs_held: the listed runs this machine may still hold (running, of the owner's agent linked to its token)
    become this connection's. The others are returned in the order listed, for run_cancel."""
    if not run_ids:
        return []
    held = set((await db.execute(
        select(AgentRun.id).join(Agent, Agent.id == AgentRun.agent_id).where(
            AgentRun.id.in_(set(run_ids)), AgentRun.status == RunStatus.running,
            Agent.runner_token_id == conn.token_id, Agent.owner_id == conn.user_id)
    )).scalars())
    conn.run_ids |= held
    return [r for r in dict.fromkeys(run_ids) if r not in held]


async def running_runs_by_token(db: AsyncSession) -> dict[tuple[uuid.UUID, uuid.UUID], set[uuid.UUID]]:
    """Running runs of agents linked to a runner token, by (token id, owner id)."""
    rows = await db.execute(
        select(Agent.runner_token_id, Agent.owner_id, AgentRun.id).join(Agent, Agent.id == AgentRun.agent_id)
        .where(AgentRun.status == RunStatus.running, Agent.runner_token_id.is_not(None)))
    out: dict[tuple[uuid.UUID, uuid.UUID], set[uuid.UUID]] = {}
    for token_id, owner_id, run_id in rows.all():
        out.setdefault((token_id, owner_id), set()).add(run_id)
    return out
```

`fail_disconnected_runs` keeps its query and `superseded` rule. It adds `if registry.conn_for_run(run.id) is not None: continue` and calls `_end_disconnected_run(db, run, owner_id, unauthorized=conn.close_code == CLOSE_UNAUTHORIZED)`.

### Code G: router grace wiring (step 8)

```python
def _holds_runs(conn: RunnerConn) -> bool:
    """A connection that ended whose running runs wait for the runner to come back instead of failing now."""
    return (grace.seconds() > 0 and conn.close_code != CLOSE_UNAUTHORIZED
            and (RESUME_CAPABILITY in conn.capabilities or grace.pending(conn.token_id)))


async def _runs_held(conn: RunnerConn, msg: RunsHeld) -> None:
    """The runner lists the runs it still holds: they are this connection's; a listed run that is no longer running
    gets run_cancel; the running runs it did not list fail; the token's deadline is settled."""
    try:
        async with SessionLocal() as db:
            stale = await claim_held_runs(db, conn, msg.runs)
        for run_id in stale:
            with contextlib.suppress(RunnerClosed):
                await conn.send(RunCancel(run_id=run_id))
        await _fail_unclaimed(conn)
    finally:
        conn.runs_held_seen = True
        grace.cancel(conn.token_id)
    await _dispatch(conn.user_id)
```

- Hello: run `await _fail_unclaimed(conn)` only when `not (RESUME_CAPABILITY in conn.capabilities and grace.seconds() > 0)`.
- `_apply`: add `elif isinstance(msg, RunsHeld): await _runs_held(conn, msg)`.
- `_cleanup(conn, inbox)`, after the drain: `if _holds_runs(conn): grace.hold(conn.token_id, conn.user_id, set(conn.run_ids))`, `else: await _fail_runs(conn)`. Keep the try/except logging as it is.

### Code H: runner outbox (`runner/internal/jobs/outbox.go`, step 12)

```go
// outbox keeps a run's messages (run_update, run_finished, run_steer_result) that could not reach the server
// while the connection is down, in order, for the next connection (MC-214).
type outbox struct {
	mu      sync.Mutex
	limit   int
	holding bool  // between a disconnect with a grace period and the next runs_held: everything waits here
	msgs    []any // protocol.RunUpdate, protocol.RunFinished, protocol.RunSteerResult values
}

func newOutbox(limit int) *outbox

// send sends msg, or keeps it: while holding, while older messages wait, or when keep is set and the send fails.
func (o *outbox) send(send func(any) error, msg any, keep bool)
func (o *outbox) hold()          // holding = true
func (o *outbox) drop()          // forget every message and stop holding
func (o *outbox) holds() bool    // holding || len(msgs) > 0
func (o *outbox) finishedRuns() []string // run ids of the queued run_finished, in order
// flush sends the queued messages in order under the lock (new ones queue behind). On a failure it keeps the rest
// and stays holding; once all are sent it stops holding.
func (o *outbox) flush(send func(any) error) error
// addLocked: at the limit, drop the oldest RunUpdate first, then the oldest RunSteerResult; never a RunFinished
// (the outbox may then grow past the limit by run_finished messages only).
func (o *outbox) addLocked(msg any)
```

`const outboxLimit = 2000`. Manager: `out *outbox` (`newOutbox(outboxLimit)` in `New`) and:

```go
// sendRun sends a run's message, through the outbox when the server gave a grace period.
func (m *Manager) sendRun(msg any) { m.out.send(m.send, msg, m.graceOn()) }
```

Lock order: `m.mu` is never held while `o.mu` is taken. `graceOn()` reads `m.grace` under `m.mu` and releases it before `out.send`.

### Code I: runner grace (`runner/internal/jobs/grace.go`, step 13)

New Manager fields:
- `GraceUnit time.Duration`: one grace second, default `time.Second` (a test hook).
- `grace time.Duration`: from the last welcome.
- `heldSent int`: the connection number `runs_held` was last sent on.
- `holdTimer *time.Timer`, `holdID int`.

```go
const reconnectCapWhileHolding = 5 * time.Second

// disconnected is conn.Client.OnDisconnect. Without a grace period every run stops, as before. With one, the runs
// keep going and their messages wait in the outbox; the timer stops them if no welcome comes in time. It is called
// again for each failed reconnect: a running timer is left alone.
func (m *Manager) disconnected(lost int) {
	m.mu.Lock()
	grace, timing := m.grace, m.holdTimer != nil
	if grace <= 0 {
		m.mu.Unlock()
		m.out.drop()
		m.StopAllUpTo(lost)
		return
	}
	m.out.hold()
	if !timing {
		m.holdID++
		id := m.holdID
		m.holdTimer = time.AfterFunc(grace, func() { m.graceExpired(id, lost) })
	}
	m.mu.Unlock()
}

// graceExpired: the server has given the runs up; stop them as a disconnect without a grace period does.
// m.ended is not moved at the disconnect itself, so a run_start still queued from the lost connection starts and
// is listed in runs_held; it moves here.
func (m *Manager) graceExpired(id, lost int) {
	m.mu.Lock()
	if id != m.holdID || m.holdTimer == nil {
		m.mu.Unlock()
		return
	}
	m.holdTimer = nil
	m.mu.Unlock()
	m.out.drop()
	m.out.hold() // until the next runs_held: the runs are stale and send nothing anyway
	m.StopAllUpTo(lost)
}

// resume handles a welcome on connection conn (0: unknown, nothing to do). It is called after HandleWelcome.
func (m *Manager) resume(conn int, w protocol.Welcome) {
	m.mu.Lock()
	m.grace = time.Duration(w.GraceSeconds) * m.GraceUnit
	if conn == 0 || (w.GraceSeconds > 0 && conn <= m.heldSent) {
		m.mu.Unlock()
		return
	}
	stopped := m.stopHoldLocked() // stops and clears holdTimer; true if one was running
	if w.GraceSeconds <= 0 {
		m.mu.Unlock()
		if stopped || m.out.holds() { // an older server: no grace any more
			m.out.drop()
			m.StopAllUpTo(conn - 1)
		}
		return
	}
	m.heldSent = conn
	m.mu.Unlock()
	if err := m.send(protocol.NewRunsHeld(append(m.heldRuns(), m.out.finishedRuns()...))); err != nil {
		return // this connection died too; its OnDisconnect starts a new timer
	}
	_ = m.out.flush(m.send)
}

// heldRuns are the runs in flight on the current generation, not abandoned, oldest id first (sorted).
func (m *Manager) heldRuns() []string

// ReconnectCap is conn.Client.ReconnectCap: 5 s while runs are held, so a 60 s grace period is not missed.
func (m *Manager) ReconnectCap() time.Duration
```

`ReconnectCap` returns `reconnectCapWhileHolding` when `m.holdTimer != nil` or `m.out.holds()`, and 0 otherwise. `Serve` sets `c.OnDisconnect = func(error) { m.disconnected(c.Session()) }` and `c.ReconnectCap = m.ReconnectCap`. `Dispatch`'s welcome case calls `m.HandleWelcome(w)`, then `m.resume(env.Conn, w)`, then the drift job as today. `Shutdown` stops the timer.

## Steps

### 1. The DB pool is configurable and bigger, and uvicorn waits longer for pongs

Files: `backend/app/core/config.py`, `backend/app/core/db.py`, `backend/Dockerfile`, `deploy/docker-compose.yml`, `docs/install.md`. New test: `backend/tests/core/test_db_pool.py`.

Test first:
- `test_pool_settings_reach_the_engine`: `engine_options(Settings(secret_key="k"*32, db_pool_size=7, db_max_overflow=3, db_null_pool=False)) == {"pool_pre_ping": True, "pool_size": 7, "max_overflow": 3}`.
- `test_null_pool_ignores_the_sizes`: with `db_null_pool=True`, the result is `{"pool_pre_ping": True, "poolclass": NullPool}`.
- `test_pool_defaults`: `Settings.model_fields["db_pool_size"].default == 20` and the same for `db_max_overflow`.

Run `BT tests/core/test_db_pool.py`. It fails with an ImportError (`engine_options`).

Implement:
- Settings: `db_pool_size: int = 20` and `db_max_overflow: int = 20`, with a comment that the worker uses 5/10 and the total must stay under PostgreSQL's `max_connections`.
- `db.py`: `def engine_options(settings) -> dict` and `engine = create_async_engine(_settings.database_url, **engine_options(_settings))`.
- Dockerfile CMD: add `"--ws-ping-timeout", "60"` after `"--workers", "1"`.
- Compose: backend environment gets `DB_POOL_SIZE: ${DB_POOL_SIZE:-20}` and `DB_MAX_OVERFLOW: ${DB_MAX_OVERFLOW:-20}`. Worker gets `DB_POOL_SIZE: "5"` and `DB_MAX_OVERFLOW: "10"`, commented "55 of PostgreSQL's 100 connections in total".
- `docs/install.md`: env table rows for `DB_POOL_SIZE` ("database connections the backend keeps open", `20`) and `DB_MAX_OVERFLOW` ("extra connections it may open in a burst", `20`).

Run BT again: pass. Then `BT tests/core`. LINT.

Commit: `fix(backend): the database pool size is a setting and defaults to 20 plus 20 (MC-214)`.

### 2. AI usage rows are written in the background, so a caller never waits for a second connection

Files: `backend/app/ai/client.py`, `backend/tests/conftest.py`, `backend/tests/ai/test_ai.py`, `backend/tests/ai/test_complete.py`, `backend/app/main.py`, `backend/app/worker.py`, `backend/app/cli.py`. New test: `backend/tests/ai/test_usage_background.py`.

Test first:
- `test_embed_does_not_wait_for_a_second_connection`:
  - Set up `small = create_async_engine(get_settings().database_url, pool_size=1, max_overflow=0, pool_timeout=1)`, `Small = async_sessionmaker(small, expire_on_commit=False)` and `monkeypatch.setattr(ai, "SessionLocal", Small)`.
  - In `async with Small() as caller:`, run `await caller.execute(text("SELECT 1"))` (the caller holds the only connection), then `model, _ = await asyncio.wait_for(ai.embed(caller, ["hello"]), 0.5)` and assert `model == ai.FAKE_EMBED_MODEL`.
  - After the block, `await ai.usage_written()` and count the `AiUsage` rows through `Small`: 1. Dispose `small` in `finally`.
- `test_a_failed_usage_write_is_logged_not_raised`: patch `ai.SessionLocal` with a callable that raises `RuntimeError`. `embed` returns; `await ai.usage_written()` does not raise; caplog contains `recording AI usage failed`.

Run `BT tests/ai/test_usage_background.py`. The first test fails with `TimeoutError` (today `_record` waits for the pool), the second with `RuntimeError`.

Implement in `client.py`:
- `_pending: set[asyncio.Task] = set()`.
- `_record(...)` becomes a plain function. It creates `asyncio.create_task(_write_usage(...))`, adds the task to `_pending` and discards it on done. It keeps the comment "its own transaction: a failed call is recorded even when the caller rolls back".
- `_write_usage` is today's body wrapped in `try/except Exception: log.exception("ai: recording AI usage failed")`.
- `async def usage_written() -> None` waits until no pending task of the running loop is left (`[t for t in _pending if t.get_loop() is asyncio.get_running_loop()]`, gathered with `return_exceptions=True`, looped).
- Every `await _record(` becomes `_record(`.

Callers:
- `conftest._truncate_tables`: `await usage_written()` before TRUNCATE.
- `test_ai.py` (before line 121's select) and `test_complete.py` (before each `select(AiUsage)`, lines ~60/74/89): `await ai.usage_written()`.
- `main.lifespan` finally: `with contextlib.suppress(Exception): await asyncio.wait_for(usage_written(), 5)` before `hub.stop()`.
- `worker._main`: after the gather, `await usage_written()`.
- `cli.py`: add `async def _main(argv)`: `try: return await run(argv)`, `finally: await usage_written()`. `__main__` calls `asyncio.run(_main(...))`.

Run `BT tests/ai tests/dashboard tests/memory tests/kb`: pass. LINT.

Commit: `fix(ai): usage rows are written in the background so a call never holds two connections (MC-214)`.

### 3. The runner socket is read continuously while a worker applies its messages

Files: new `backend/app/runner/inbox.py` (Code A), `backend/app/runner/router.py` (Code C). New: `backend/tests/runner/live.py`, `backend/tests/runner/test_inbox.py`, `backend/tests/runner/test_inbox_unit.py`.

`tests/runner/live.py`:
- `live_server(ping_interval=0.2, ping_timeout=0.4, max_queue=4)` is an async context manager. It picks a free port, builds `uvicorn.Config(create_app(), host="127.0.0.1", port=port, ws="websockets", ws_ping_interval=…, ws_ping_timeout=…, ws_max_queue=…, lifespan="on", log_level="warning")`, runs `uvicorn.Server(config).serve()` as a task, waits for `server.started` (5 s at most), and yields `"ws://127.0.0.1:<port>"`. On exit it sets `should_exit` and awaits the task (10 s at most).
- `async def running_runs(client, db, n) -> tuple[User, dict, list[uuid.UUID]]`:
  - Make a user and the project PAY (`make_project`), log in with the httpx `client`.
  - `POST /api/tokens {"name":"laptop","scopes":["runner"]}`, then `POST /api/agents {"program":"claude_code","max_concurrent_runs":n,"runner_token_id":<id>}` and its bindings (`/repo`).
  - Create n tasks assigned to the agent, `queue_run` each one, then set them all `running` in the DB.
  - Return the user, `{"Authorization": "Bearer <secret>"}` and the run ids.
- `async def runner_socket(ws_base, headers)`: `websockets.asyncio.client.connect(ws_base + "/api/runner/ws", additional_headers=headers, ping_interval=None)`, plus a task that reads every frame into a list (so the client always reads).

Tests in `test_inbox.py`:
- **`test_a_stalled_handler_does_not_close_the_runner_socket`** (acceptance 1):
  - Patch `rr._on_this_machine` with a wrapper that awaits `release` and then calls the original.
  - Over a live server, send 100 `run_update`s for one run (`kind "tool"`, `{"tool_kind":"read","title":f"Read {seq}","status":"completed"}`, seq 1..100).
  - Sleep 2 s (five ping timeouts). Assert `ws.state is State.OPEN` and `await asyncio.wait_for(await ws.ping(), 1)` (the server still reads and answers).
  - Set `release`. Poll the DB until there are 100 `agent_tool` events (10 s). Assert the socket is still OPEN.
- `test_a_slow_handler_is_not_closed_as_idle_while_frames_arrive`: patch `rr.IDLE_TIMEOUT_SECONDS = 0.5`, stall as above. Send one run_update, then a heartbeat every 0.1 s for 1.5 s. The socket is still OPEN.

**Confirm that acceptance 1 fails on today's code.** Commit nothing yet. Write `live.py` and `test_inbox.py` first and run `BT tests/runner/test_inbox.py`. Both tests fail: the socket is closed (1011 keepalive ping timeout, then 4408 idle). Note this in the commit body.

`test_inbox_unit.py` uses a fake socket whose `receive()` reads from an `asyncio.Queue`, and an `Inbox` with recording handlers:
- Messages are applied in order.
- An invalid frame gives `inbox.end == End(invalid=True)` after the messages before it are applied.
- A disconnect gives `End(invalid=False)`.
- A raising handler is logged and the next message is still applied.
- `stop()` while a handler runs lets it finish.

Implement Codes A and C. Run `BT tests/runner/test_inbox.py tests/runner/test_inbox_unit.py tests/runner tests/agent_runs tests/hub`: pass. `test_failed_welcome_send_ends_serve_quietly` must still pass (`_serve` creates its own inbox). LINT.

Commit: `fix(runner): the server reads the runner socket while a worker applies its messages (MC-214)`.

### 4. Streamed run updates are applied in batches

Files: `backend/app/agent_runs/service.py`, `backend/app/runner/router.py` (Code D). New: `backend/tests/agent_runs/test_batch_updates.py`.

Test first (helpers: `_running`, `_events`, `_row` from `tests.agent_runs.test_updates`):
- `test_a_batch_is_one_transaction_with_one_task_updated_per_task`:
  - Two running runs on two tasks. Patch `app.agent_runs.service.publish` with a recorder that also calls the original.
  - Call `apply_updates(db, me.id, [3 updates for run A, 2 for run B, interleaved])`, then commit.
  - There are 5 events, the recorded `task.updated` events are exactly one per task, and `created_at` strictly increases in the batch's order.
- `test_a_batch_keeps_the_checks_per_update`: a duplicate seq, an older seq and a stranger's run inside a batch are ignored (as in `test_duplicate_seq_ignored`).
- `test_a_failing_batch_falls_back_to_one_by_one`: call `rr._run_updates` with a `_fake_conn` (from `tests.agent_runs.test_dispatch`) and `rr.apply_updates` patched to raise. The events are still stored, and caplog shows `applying them one by one`.
- `test_updates_from_another_machine_are_ignored`: a conn whose token is not the agent's. `_run_updates` stores nothing.
- `test_inbox_unit.py` additions (patch `inbox.BATCH_MAX = 3` and `BATCH_WINDOW_SECONDS = 0.05`):
  - 5 updates, a heartbeat and 2 updates give update batches [3], [2], then the heartbeat, then [2].
  - Two updates 0.2 s apart give two batches.
- **`test_two_runs_streaming_on_one_socket_both_finish`** (acceptance 2) in `test_inbox.py`:
  - Over `live_server()`, patch `rr.apply_updates` with a wrapper that sleeps 0.3 s first (a slow DB).
  - Use `running_runs(n=2)`. Send 50 updates per run, interleaved, then a `run_finished` (completed) for each.
  - Both runs end `completed` (10 s), the socket was never closed, and each run's `agent_tool` events ordered by `(created_at, id)` have titles `Read 1..50` in order.

Run `BT tests/agent_runs/test_batch_updates.py tests/runner/test_inbox_unit.py tests/runner/test_inbox.py`. It fails with an ImportError (`apply_updates`).

Implement Code D. Run again: pass. Then `BT tests/agent_runs tests/runner tests/workflow/test_engine.py`. LINT.

Commit: `fix(runner): run updates that arrive together are stored in one transaction (MC-214)`.

### 5. Run messages queued before a connection ends are applied before its runs are dealt with

Files: `backend/app/runner/inbox.py` (Code B), `backend/app/runner/router.py`. Tests: `backend/tests/runner/test_inbox.py`, `test_inbox_unit.py`.

Test first:
- `test_a_run_finished_queued_before_the_socket_is_replaced_completes_the_run` (TestClient, `tc_factory(lifespan=True)`, `_setup`, `_start`, `_hello`, `_avail`):
  - Run dispatched and running. Patch `rr._on_this_machine` to stall on `release`.
  - The first socket sends a `run_update` and then a `run_finished` (completed).
  - Open a second socket with the same token. The first gets 4409, and the old `_serve` returns while its worker is stalled.
  - Set `release`. The run ends `completed`, not `failed`/`runner_disconnected`.
- `test_unauthorized_close_applies_nothing`: the same, but revoke the token (`DELETE /api/tokens/{id}`) instead of a second socket. The run ends `cancelled`, reason `runner_unauthorized`.
- Unit test: after `stop()`, `drain()` applies only `RUN_MESSAGES` in order (a hello in between is dropped), with updates batched.

Run BT on these: the first test fails (the run ends `failed` because the queued `run_finished` was dropped).

Implement Code B. In `_cleanup(conn, inbox)`, first: `if inbox is not None and conn.close_code != CLOSE_UNAUTHORIZED:` `try: await inbox.drain()`, `except Exception: log.exception("runner disconnect: applying queued run messages failed")`. Then today's `_fail_runs` and the availability publish.

Run again: pass. `BT tests/runner tests/agent_runs`. LINT.

Commit: `fix(runner): a run_finished that arrived before a disconnect still ends its run (MC-214)`.

### 6. The welcome carries the grace period and the server accepts runs_held

Files:
- `backend/app/core/config.py`: `runner_grace_seconds: int = 60`.
- `backend/app/runner/grace.py` (new, only `seconds()` and `MARGIN_SECONDS = 30` from Code E for now).
- `backend/app/runner/protocol.py`.
- `backend/app/runner/registry.py`.
- `backend/app/runner/router.py`.
- `deploy/docker-compose.yml`: backend `RUNNER_GRACE_SECONDS: ${RUNNER_GRACE_SECONDS:-60}`.
- `docs/install.md`: row `RUNNER_GRACE_SECONDS` ("how long a runner that lost its connection may keep its runs going, in seconds; 0 turns it off", `60`).
- `backend/tests/runner/test_runner_ws.py`.
- New: `backend/tests/runner/test_resume_protocol.py`.

Test first:
- `test_welcome_carries_the_grace_period`: the welcome has `grace_seconds == 60`. With `monkeypatch.setattr(get_settings(), "runner_grace_seconds", 0)` it is 0.
- `test_runs_held_validates`: `runner_message.validate_python({"type":"runs_held","runs":[str(uuid4())]})` is a `RunsHeld`. 201 ids, an extra field or a non-uuid raise `ValidationError`. `runs` defaults to `[]`.
- `test_runs_held_does_not_close_the_socket`: send `runs_held` with `[]`, then a hello. `_wait_status(... "online")`.
- Update `test_welcome_lists_agents_and_bindings`: the expected dict gains `"grace_seconds": 60`.

Run `BT tests/runner/test_resume_protocol.py tests/runner/test_runner_ws.py`: fails (no field, unknown type gives 4400).

Implement:
- `Welcome.grace_seconds: int = 0`.
- `class RunsHeld(_FromRunner): type: Literal["runs_held"]; runs: list[uuid.UUID] = Field(default=[], max_length=200)`, added to `RunnerMessage`.
- `build_welcome` passes `grace_seconds=grace.seconds()`.
- `registry.py`: `RESUME_CAPABILITY = "resume/1"` with the comment "the runner keeps its runs through a drop of up to welcome.grace_seconds and lists them in runs_held".
- `RunnerConn.runs_held_seen = False` ("this connection's runner sent runs_held").
- `_apply` ignores `RunsHeld` for now (comment: step 8).

Run `BT tests/runner tests/agents/test_agent_model.py`: pass. LINT.

Commit: `feat(runner): the welcome says how long a runner may hold its runs, and runs_held is accepted (MC-214)`.

### 7. Run service functions for held runs

Files: `backend/app/agent_runs/service.py` (Code F). New: `backend/tests/agent_runs/test_held_runs.py`.

Test first (helpers: `_running`, `_row` from `tests.agent_runs.test_updates`; `_fake_conn`, `_FakeSocket` from `tests.agent_runs.test_dispatch`; always `registry._conns.pop(me.id, None)` in `finally`):
- `test_claim_held_runs_claims_running_runs_of_the_machine`: two running runs plus one set `completed`, linked via `_fake_conn`. `claim_held_runs(db, conn, [a, done, uuid4(), b])` returns `[done, <random>]`, and `conn.run_ids == {a, b}`.
- `test_fail_held_runs_ends_runs_no_connection_holds`:
  - Run a is not held: it fails `runner_disconnected` and an `agent_offline` Notification exists.
  - Run b has `cancelled_by` set: it ends `cancelled`.
  - Run c is in a live conn's `run_ids`: it stays `running`.
- `test_fail_held_runs_counts_remembered_runs_after_an_unlink`: unlink the agent (`runner_token_id=None`). `fail_held_runs(db, token_id, me.id, {a})` still fails a.
- `test_fail_disconnected_runs_skips_a_run_a_live_connection_holds`: two conns of the same token, the run in the live one's `run_ids`. `fail_disconnected_runs(db, old_conn)` leaves it running.
- `test_running_runs_by_token_groups_by_token_and_owner`.

Run `BT tests/agent_runs/test_held_runs.py`: ImportError.

Implement Code F. Refactor `fail_disconnected_runs` to use `_end_disconnected_run`. Run `BT tests/agent_runs tests/runner`: pass. LINT.

Commit: `feat(runs): claim, fail and list the runs a dropped runner held (MC-214)`.

### 8. A dropped resume/1 runner's runs wait for it, and runs_held settles them

Files: `backend/app/runner/grace.py` (rest of Code E), `backend/app/runner/router.py` (Code G). New: `backend/tests/runner/test_grace.py`.

Test set-up: `tc_factory(lifespan=True)`, `_setup`, `_start`, `_hello(…, capabilities=CURRENT_CAPABILITIES + ("resume/1",))`. Set `get_settings().runner_grace_seconds` and `grace.MARGIN_SECONDS` with monkeypatch. Workflow helpers come from `tests.workflow.test_engine` (`_started`, `_runs`, `_wf`, `_until`) and `_next_of` from `tests.agent_runs.test_run_guards`.

Test first:
- **Acceptance 3a** `test_a_drop_inside_the_grace_period_fails_nothing`:
  - Grace 60. Workflow run started and running. Leave the socket.
  - 0.5 s later the run is still `running`, the task has no `agent_run_failed` event, no `agent_offline` Notification exists, `wf.failures == 0`, and the agent is `offline`.
  - Reconnect: the welcome has `grace_seconds == 60`. Send hello(resume), then `runs_held [run]`, a `run_update` seq 1 and `run_finished` completed.
  - The run is `completed` and `agent_message` is stored.
- **Acceptance 3b** `test_a_runner_that_does_not_return_fails_at_the_deadline`: grace 1 and margin 0. Workflow run, drop. Wait until failed with `runner_disconnected` (5 s). `wf.failures == 1` and an `agent_offline` Notification exists.
- `test_runs_held_cancels_a_run_no_longer_running_and_fails_unlisted_ones`:
  - Run A is dispatched. Run B is another task's run set `running` in the DB. Drop.
  - Cancel A via `POST /api/agent-runs/{id}/cancel`: it is cancelled at once.
  - Reconnect with `runs_held [A]`. The socket receives `{"type":"run_cancel","run_id":A}`, and B fails with `runner_disconnected`.
- `test_a_runner_without_resume_fails_at_once` (grace 60, no resume): failed at once, as today.
- `test_unauthorized_close_cancels_at_once_even_with_resume`: revoke while connected gives `cancelled`/`runner_unauthorized`.
- `test_hello_from_a_resume_runner_leaves_running_runs_for_runs_held`: an orphan running run is still `running` after hello(resume), and fails after `runs_held []`.
- `test_a_replaced_connection_keeps_its_runs`: a second socket with the same token sends hello(resume) and `runs_held [run]`. The run is still `running` 0.5 s later, and its later `run_finished` completes it. This is the network cut the server noticed late.
- `test_the_deadline_waits_for_runs_held_from_a_live_runner`: grace 0.3 and margin 0. Drop, reconnect with hello(resume) and no `runs_held`. 1 s later the run is still `running`. After `runs_held [run]` it is still `running`.
- `test_grace_zero_fails_at_once`: setting 0. The welcome has `grace_seconds 0`, and a resume runner's drop fails the run at once.

Run `BT tests/runner/test_grace.py`: the runs fail at once and runs_held does nothing.

Implement Code E (rest) and Code G. In `main.lifespan` finally, call `grace.cancel_all()` before `hub.stop()`.

Run `BT tests/runner tests/agent_runs tests/workflow/test_engine.py`: pass. LINT.

Commit: `feat(runner): runs of a dropped runner wait out the grace period and runs_held picks them up (MC-214)`.

### 9. At startup every runner token with running runs gets a deadline

Files: `backend/app/main.py`. New: `backend/tests/runner/test_grace_startup.py`.

Test first:
- `test_a_running_run_fails_at_the_deadline_after_a_restart`:
  - With a non-lifespan client, set up the manager, project, token and agent (`tc_factory()`, `_manager_with_project`, `_setup`), `await queue_run(task_key)`, and set the run `running`.
  - Set grace 0.3 and margin 0. Enter `tc_factory(lifespan=True)`.
  - The run fails with `runner_disconnected` within 5 s.
- `test_a_runner_that_returns_after_a_restart_keeps_its_run`: grace 2 and margin 0. After startup, connect with hello(resume) and `runs_held [run]`. 2.5 s later the run is still `running`.

Run `BT tests/runner/test_grace_startup.py`: the first test fails (the run stays running).

Implement: in `lifespan`, after the startup session commits and after `hub.start`, call `await grace.hold_at_startup()` (log and continue on exception).

Run again: pass. `BT tests/core/test_startup.py tests/agent_runs/test_machine_runs.py`. LINT.

Commit: `feat(runner): after a restart, running runs wait for their runner and fail if it never returns (MC-214)`.

### 10. Runner protocol: grace_seconds, resume/1 and runs_held

Files: `runner/internal/protocol/protocol.go`, `protocol_test.go`.

Test first:
- `TestRunsHeldShape`: `NewRunsHeld(nil)` marshals to `{"type":"runs_held","runs":[]}`.
- `TestRunsHeldIsBounded`: 250 ids give 200.
- `TestWelcomeCarriesGraceSeconds`: decode `{"type":"welcome","user_id":"u","agents":[],"grace_seconds":60}` and get `GraceSeconds == 60`.
- The welcome key list test stays `{"agents","type","user_id"}` (omitempty).

Run `GO protocol 'RunsHeld|GraceSeconds'`: does not compile.

Implement:
- `TypeRunsHeld = "runs_held"`.
- `CapabilityResume = "resume/1"`, commented as Code I describes. It is **not** in `NewHello` yet; step 13 adds it.
- `const RunsHeldLimit = 200`.
- `type RunsHeld struct { Type string \`json:"type"\`; Runs []string \`json:"runs"\` }`.
- `NewRunsHeld` (non-nil, the first 200).
- `Welcome.GraceSeconds int \`json:"grace_seconds,omitempty"\`` ("how long the runner may hold its runs after a drop; 0: stop them at once").

Run again: pass. `go vet ./... && go test ./...`.

Commit: `feat(runner): protocol types for the grace period and runs_held (MC-214)`.

### 11. The reconnect delay can be capped

Files: `runner/internal/conn/conn.go`, `conn_test.go`.

Test first: `TestReconnectCapShortensTheDelay`. `BackoffBase` and `BackoffMax` are `time.Hour`, `Jitter` returns 0.5, and `ReconnectCap` returns 20 ms. The server closes 1011 after the first connection. A second connection arrives within 2 s.

Run `GO conn ReconnectCap`: does not compile.

Implement the field `ReconnectCap func() time.Duration` with the comment "if set and > 0, no reconnect waits longer (the manager holds runs)". In `Run`, after `backoffDelay`, apply the cap.

Run again: pass. `go test ./...`.

Commit: `feat(runner): the connection's reconnect delay can be capped (MC-214)`.

### 12. Run messages go through an outbox

Files: new `runner/internal/jobs/outbox.go` (Code H), `outbox_test.go`; `manager.go`, `steer.go`.

Test first (`outbox_test.go`):
- `TestOutboxSendsDirectlyWhenNotHolding`.
- `TestOutboxKeepsFailedSendsOnlyWhenAsked`: `keep=false` drops the message, `keep=true` queues it.
- `TestOutboxHoldsInOrderAndFlushes`: hold, 3 messages, flush. They are sent in order and holding is off.
- `TestOutboxFlushFailureKeepsTheRest`.
- `TestOutboxIsBoundedAndNeverDropsRunFinished`: limit 3 with update, finished, update, update, update. It keeps the finished and the 2 newest updates.
- `TestOutboxFinishedRuns`.

Run `GO jobs Outbox`: does not compile.

Implement Code H:
- Add `grace time.Duration` (guarded by `m.mu`) and `graceOn()` to the Manager.
- Replace `_ = r.m.send(protocol.NewRunUpdate…)` (`sendLocked`), `_ = m.send(rf)` (`finishRun`) and both sends in `steer.go` (lines ~65, ~75) with `sendRun`.

Grace is always 0 here, so behaviour is unchanged. Run `GO jobs Outbox`, then `go vet ./... && go test ./...`: pass.

Commit: `refactor(runner): a run's messages go through an outbox (MC-214)`.

### 13. The runner keeps its runs through a drop and lists them on reconnect

Files: new `runner/internal/jobs/grace.go` (Code I), `grace_test.go`; `manager.go` (Serve, Dispatch, Shutdown, fields); `protocol.go` (`CapabilityResume` in `NewHello`); `protocol_test.go`.

Test first (`grace_test.go`, built on `newEnvWithCache`). Add `func (e *env) welcomeGrace(maxRuns, grace int)`, which is `welcomeAs` with `GraceSeconds`. Tweak `m.GraceUnit = 100*time.Millisecond`.
- **`TestDropWithGraceKeepsTheRunAndResumes`**:
  - Scenario `[{"say":"before"},{"sleep_ms":1500},{"plan":[["after","in_progress"]]},{"say":"done"}]`. `welcomeGrace(1, 50)` makes the runner send `runs_held` with `[]` on connection 1.
  - Start `run-g` and wait for an update. `srv.RejectWith(1011)`, `srv.Close(1011, "blip")`, sleep 1 s, `RejectWith(0)`, `WaitNthFrame(hello, 2)`, `welcomeGrace(1, 50)`.
  - On the new connection, the first run frame is `runs_held` `["run-g"]`, followed by the buffered updates with strictly increasing seq and then `run_finished` completed.
  - `readReport().Cancelled` is false.
- `TestGraceTimerStopsTheRuns`: `welcomeGrace(1, 2)` (200 ms). Reject and close, then wait until `readReport().Cancelled`. Accept again and welcome: `runs_held` is `[]` and no frame for the run appears on the new connection.
- `TestWelcomeWithoutGraceSendsNoRunsHeld`: the existing flow (`welcome`). No `runs_held` frame is ever sent.
- `TestReconnectCapWhileHolding`: `ReconnectCap()` is 0 at first, 5 s after `disconnected` with grace, and 0 after the resume.
- `TestHelloAdvertisesResume` in `protocol_test.go`.

Run `GO jobs 'Grace|Resume|ReconnectCap'` and `GO protocol Resume`: fail.

Implement Code I. Add `CapabilityResume` to `NewHello`'s list. Update the comment on `Serve`.

Run again, then `go vet ./... && go test ./...`. `TestDisconnectStopsRuns`, `TestRetriedRunWaitsForTheStoppedRunOfTheSameTask` and `TestRunStartFromLostConnectionIsNotLaunched` must still pass, because their welcome has no grace.

Commit: `feat(runner): runs survive a short disconnect and are listed in runs_held on reconnect (MC-214)`.

### 14. A run_start for a task with a live run cancels the old run

Files: `runner/internal/jobs/manager.go`, `manager_test.go`.

Test first: `TestRunStartForATaskWithALiveRunCancelsTheOldRun`.
- `newEnvWithCache(t, sleeping, 2, …)`. Start `run-1` on `MEG-1` and wait for an update.
- `t.Setenv("FAKEAGENT_SCENARIO", `[{"say":"again"}]`)`, then start `run-2` on `MEG-1`.
- `readReport().Cancelled` becomes true. `run-2` finishes `completed` with summary `again`.
- No `run_finished` for `run-1` is ever sent, and no `run_update` of `run-1` arrives after `run-2`'s first.

Run `GO jobs LiveRunCancels`: run-2 starts at once beside run-1, so the assertions fail.

Implement:
- `run.abandoned bool` (guarded by `m.mu`). `stale()` returns `r.gen != r.m.gen || r.abandoned`.
- In `handleRunStart`'s loop, a run with `r.gen == m.gen && !r.abandoned && r.agent == rs.AgentID && r.task == rs.Task.Key` is marked abandoned, appended to `prev`, collected for cancelling and not counted toward the limit.
- After unlocking, call `m.requestCancel` on each collected run.
- `heldRuns` already skips abandoned runs.

Run again, then `go vet ./... && go test ./...`: pass.

Commit: `fix(runner): a new run for a task stops the run the server gave up on, so they never share a worktree (MC-214)`.

## Final verification

1. From `backend/`, run the whole suite: `megoocolab-runner services run test -- uv run pytest -q -n auto`. The only known flake is `test_dashboard_answers_under_300ms_with_10k_tasks`.
2. From `runner/`: `go vet ./... && go test ./...`.
3. Requirement map:

| Requirement | Step |
|---|---|
| Socket read apart from handling | 3 |
| Acceptance 1 (stall over 20 s, pings answered) | 3 |
| Idle close fixed | 3 |
| Batches (250 ms / 200, one transaction, one publish per task, fallback, machine check) | 4 |
| Acceptance 2 | 4 |
| Queued `run_finished` before a drop | 5 |
| Grace protocol | 6, 10 |
| Server grace and `runs_held` | 7, 8 |
| Acceptance 3 | 8 |
| Startup deadlines | 9 |
| Runner outbox, timer, `runs_held`, reconnect cap, safety net | 11–14 |
| Pool settings and docs | 1, 6 |
| AI usage rows | 2 |
| Uvicorn flag | 1 |

4. By hand, with a runner built from `runner/` and the stack built from this branch:
   - Two tasks in parallel on one runner both finish, and `~/.cache/megoocolab/logs/runner.log` has no `keepalive ping timeout`.
   - A backend container restart in the middle of a run does not fail it.
   - A 30 s network cut in the middle of a run does not fail it.
5. The runner version moves from 0.12.0 to 0.13.0 at release time, not on this branch.
