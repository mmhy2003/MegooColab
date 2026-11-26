# MC-214 design: the runner socket survives load, and runs survive a short disconnect

## Goal

Two runs on one runner no longer close its socket: the server keeps reading the socket and answering pings however slow the database is. When the socket does drop (network, a backend restart or deploy), the runs keep going for a grace period and are picked up again when the runner reconnects, instead of all failing at once.

## What the code showed

- **The socket.** `_serve` (`backend/app/runner/router.py`) awaits `_handle()` inline before it calls `ws.receive()` again. When one handler waits 30 s for a DB connection, uvicorn's queue of 32 frames fills, it stops reading, pongs go unread, and it closes with `1011 keepalive ping timeout`.
- **A second way to lose the socket.** `conn.touch()` runs only when a message is handled, not when it arrives. A handler slower than 45 s gets the runner closed as idle (`4408`).
- **What emptied the pool.** `backend/app/ai/client.py`: `embed()` and `complete()` query on the caller's session (which checks out its connection), wait for the provider, and then `_record()` opens a **second** pooled connection for the usage row. With the pool empty, every caller waits 30 s for the second connection while holding the first. `kb_search`, `search_memory`, `ask_memory`, `find_answer` and the prompt building at the end of every run go through it. `current_session` is only where other requests then time out.
- **Batching.** The runner already batches message text (`acpclient`, every 1.5 s). Tool, permission, command, plan and file updates go one by one, each in its own transaction with its own `task.updated`.
- **Disconnect.** `_cleanup` fails the runs at once (`fail_disconnected_runs`), and the runner cancels its agents at once (`OnDisconnect` → `StopAllUpTo`). Hello cannot carry new fields (`extra="forbid"`), and the runner sends hello before it reads the welcome.

## Decisions

| Decision | Chosen | Rejected, and why |
|---|---|---|
| Scope | Both pieces in this design (your answer) | Server fixes now and the grace period later |
| Where messages are applied | One worker per connection: total order, at most one DB connection per runner | One worker per run: more DB connections at once, and ordering rules between workers |
| Batching | Server only: 250 ms window, at most 200 updates | Runner too: text is already batched there, and a server batch also covers older runners |
| Grace period | 60 s, one setting; the server waits 30 s longer | 120 s, 300 s |
| 3-retry rule | Unchanged. A drop inside the grace period fails nothing. After it, `runner_disconnected` counts as a failure as today | `runner_disconnected` never counts |
| AI usage rows | Written by a background task, so a caller never waits for a second connection | Only a bigger pool |
| How the runner says which runs it holds | A new message, `runs_held`, sent after the welcome | A field on hello: an older server would close the socket with 4400 on every reconnect |
| Prompt building under the task and workflow locks | A follow-up task (you agreed) | Doing it here: it changes the workflow engine |

## Architecture

### 1. Reading is separate from handling (backend)

New module `backend/app/runner/inbox.py`, one `Inbox` per connection:

- **Reader task.** The only caller of `ws.receive()`. For each frame it calls `conn.touch()`, validates the frame (`runner_message.validate_python`, no I/O) and puts the message on a queue. A disconnect or an invalid frame is put on the queue as an end marker, and the reader stops.
- **Queue.** Bounded at `INBOX_MAX = 2000` messages. When it is full the reader waits (and logs one warning for the connection). That is today's behaviour, 60 times later.
- **Worker task.** Takes messages in order and applies them with today's `_handle` logic. When it reaches an end marker, the connection ends: quietly for a disconnect, with `4400` for an invalid frame. Messages before the marker are applied first, as today.

`_serve` keeps its loop for hub events, the idle check, the token re-check and "replaced". It no longer touches `ws.receive()`. It waits for the worker to finish instead.

**When a connection ends**, `_cleanup` first applies the run messages still on the queue (`run_update`, `run_finished`, `run_steer_result`), in order, and only then deals with the runs. So a `run_finished` that arrived just before the drop is never turned into `runner_disconnected`. Other queued messages (hello, availability, Tool Hub reports) are dropped: they describe a connection that is gone. After a `4401` close nothing is applied.

### 2. Batched run updates (backend)

When the worker's next message is a `run_update`, it also takes the `run_update`s that follow, until a different message is next, 200 are collected, or 250 ms have passed since the first (`BATCH_WINDOW_SECONDS`, `BATCH_MAX`, module constants so tests can change them).

New `apply_updates(db, user_id, updates)` in `backend/app/agent_runs/service.py` applies the batch in one transaction with the same checks per update as `apply_update` (owner, running, newer `seq`), and publishes `task.updated` once per task. `_on_this_machine` is checked once per run in the batch. If the transaction fails, each update is applied again alone, in its own transaction, as today.

### 3. Grace period (backend and runner)

**Protocol** (`backend/app/runner/protocol.py`, `runner/internal/protocol/protocol.go`):

- `welcome.grace_seconds` (int, 0 = off): how long the runner may hold its runs after a drop. An older runner ignores the field.
- Capability `resume/1` in hello.
- New runner message `runs_held {type, runs: [run_id]}` (at most 200). A `resume/1` runner sends it once per connection, right after that connection's first welcome with `grace_seconds > 0`, also when the list is empty.

**Server** (new `backend/app/runner/grace.py`; `router.py`, `agent_runs/service.py`):

- **A connection ends.** If the runner has `resume/1`, the grace period is on and the close code is not `4401`: the runs are not failed. A deadline is set for the runner's token at `grace + 30 s`. Agents go offline at once, as today; their runs stay `running`. Otherwise the runs fail at once, as today.
- **Hello** from a `resume/1` runner no longer runs `fail_unclaimed_runs`; `runs_held` does.
- **`runs_held` arrives.** Each listed run that is `running` and belongs to an agent linked to this token is added to `conn.run_ids`. For each other listed run the server sends `run_cancel`. Then `fail_unclaimed_runs` fails the running runs the runner did not list, the token's deadline is cancelled, and queued runs are dispatched.
- **The deadline passes.** The running runs of that token that no live connection holds end exactly as `fail_disconnected_runs` ends them today (`runner_disconnected`, the `agent_offline` notification, a requested cancel completes). If a live `resume/1` connection of the token has not sent `runs_held` yet, the deadline does nothing: that message settles it.
- **Startup** (`backend/app/main.py`). Each runner token with `running` runs gets a deadline. Runs therefore survive a backend restart when the runner is back in time, and a run whose runner never returns no longer stays `running` for ever.
- `fail_disconnected_runs` skips a run that a live connection holds.

**Runner** (`runner/internal/jobs`, `runner/internal/conn`):

- The manager remembers `grace_seconds` from the last welcome. On a disconnect with a grace period it does not call `StopAllUpTo`. It starts a timer. If the timer fires first, it stops everything as today.
- **Outbox.** A `run_update`, `run_finished` or `run_steer_result` that cannot be sent is kept, in order (at most 2000; the oldest `run_update` is dropped first, a `run_finished` never). While the outbox is not empty, new run messages go to it.
- **On the first welcome of a new connection** with a grace period: stop the timer, send `runs_held` (the runs in flight plus the runs with a `run_finished` in the outbox), then send the outbox.
- **Reconnect delay.** While the manager holds runs, the delay is capped at 5 s (new hook on `conn.Client`). Today's backoff would try at about 31 s and then 61 s, which misses a 60 s grace period.
- **Safety net for the worktree.** A `run_start` for a task that still has a live run of the same agent means the server gave that run up. The old run is cancelled and sends nothing more, and the new run waits for it to end (the existing `prev` mechanism).

The 30 s margin on the server exists because each side notices a dead network at its own time (the runner within about 25 s, the server within about 45 s). With the margin the server never gives up a run that the runner still holds.

### 4. Database pool and AI usage rows (backend)

- `backend/app/core/config.py`: `db_pool_size = 20`, `db_max_overflow = 20` (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`), passed to `create_async_engine` in `core/db.py`; ignored with `DB_NULL_POOL`. `deploy/docker-compose.yml` sets the worker to 5 and 10, so the total is 55 of PostgreSQL's 100. `docs/install.md` gets the two rows, and `RUNNER_GRACE_SECONDS`.
- `ai/client.py`: `_record` runs as a background task (kept in a module set so it is not collected). `usage_written()` waits for the pending ones; the backend's shutdown, `worker.py`, `cli.py` and the tests call it.

### 5. Uvicorn (config)

`backend/Dockerfile`: add `--ws-ping-timeout 60`. `--ws-max-queue` stays at its default: the app now reads every frame as it arrives, so that queue no longer fills.

## Data and interfaces

- No database migration.
- Settings: `DB_POOL_SIZE` (20), `DB_MAX_OVERFLOW` (20), `RUNNER_GRACE_SECONDS` (60, 0 = off).
- Protocol: `welcome.grace_seconds`, capability `resume/1`, runner message `runs_held`.
- Compatibility. An older runner with the new server: fixes 1, 2, 4 and 5 apply, and a disconnect behaves as today. The new runner with an older server: no `grace_seconds` in the welcome, so it stops its runs at once and never sends `runs_held`.
- The grace period needs a new runner version (0.12.0 → 0.13.0 at release time).

## Error handling and edge cases

- **Cancel during the grace period.** `cancel_run` finds no connection and cancels at once, as today. When the runner returns and lists the run, it gets `run_cancel`; its late `run_finished` only fills in the summary and session, as today.
- **A run finishes while disconnected.** Its `run_finished` waits in the outbox and the run is listed in `runs_held`, so the server does not fail it before the report arrives.
- **A message lost in transit just before the drop.** A lost update leaves a gap in the activity feed. A lost `run_finished` means the run is not listed on reconnect and fails with `runner_disconnected`; the retry resumes the stored session, as today.
- **The runner gave up first** (grace period over on its side). It sends an empty `runs_held` and the server fails the runs at once.
- **Another runner signs in with the same token** (`4409`). The old runner stops for good, as today. The new one lists no runs, so the old one's runs fail.
- **Token revoked during the grace period.** The runner cannot reconnect (`4401`); the runs fail at the deadline.
- **MCP calls during the grace period** keep working: they go over HTTP and the run token stays valid while the run is `running`.
- **Agent shown offline with a run still running** during the grace period. No UI change in this task.
- **A message handler raises.** Caught and logged per message, as today; the worker goes on.
- **`RUNNER_GRACE_SECONDS=0`.** Both sides behave as today.

## Testing

Backend (pytest), written first:

- **Acceptance 1.** A real uvicorn server on a free port with a short ping interval and timeout and `ws_max_queue=4`. The handler is blocked for several ping timeouts while a client sends 100 updates. The socket stays open, pings are answered, and after the release every update is stored. The plan confirms that this test fails on today's code.
- A handler blocked longer than the idle timeout does not close the connection as idle while frames keep arriving.
- **Acceptance 2.** Two runs stream interleaved updates over one socket with slow DB sessions: both finish as completed and their events are in `seq` order.
- Batching: a burst for two tasks is one transaction with one `task.updated` per task; a failing batch falls back to one by one; an update from another machine is ignored.
- A `run_finished` queued before a disconnect ends the run as completed, not `runner_disconnected`.
- **Acceptance 3.** Drop, reconnect and `runs_held` inside the grace period: the run is still `running`, with no failure event, no `agent_offline` notification and `wf.failures` unchanged; later updates and the finish are accepted. No return: the run fails after the deadline and counts one failure.
- `runs_held` with a run that is no longer running gets `run_cancel`; an unlisted running run fails.
- A runner without `resume/1`, and a `4401` close: at once, as today.
- Startup: a running run fails at the deadline, or is claimed if the runner returns.
- Pool settings reach the engine. With a pool of one connection, `embed` no longer waits for a second one.

Runner (Go, `internal/testserver`):

- After a welcome with `grace_seconds`, a closed socket leaves the runs going. On reconnect the server sees `runs_held`, then the buffered updates in order, then `run_finished`.
- The grace timer firing stops the runs as today. A welcome without `grace_seconds` does too, and no `runs_held` is sent.
- The reconnect delay is capped while runs are held. The outbox keeps its bound and never drops a `run_finished`.
- A `run_start` for a task with a live run cancels the old run and waits for it.

By hand, with the built runner: two tasks in parallel on one runner both finish with no `keepalive ping timeout` in `runner.log`; a backend container restart and a 30 s network cut in the middle of a run do not fail it.

## Out of scope

- Building the next run's prompt outside the task and workflow locks (follow-up task below).
- Batching on the runner, and one worker per run.
- A "reconnecting" state in the UI.
- Changing the 3-retry rule.
- More than one backend process.