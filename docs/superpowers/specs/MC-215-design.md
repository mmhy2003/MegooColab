# MC-215 design: build the Knowledge Base and Memory sections after the commit

## Goal

No embedding call is made while a task, workflow or run row is locked. `enqueue` builds the prompt from DB reads only. The Knowledge Base and Memory sections are added after the transaction commits, just before the run is sent.

## Decisions

| Decision | Chosen | Rejected |
|---|---|---|
| Where the slow part runs | After the commit, in `dispatch_pending` (you chose A) | B: a stored query vector per task (new table, invalidation, keyword-only matches when it is not ready). C: building before the locks (about 25 call sites, wasted calls, easy to forget) |
| How a run is marked | A nullable column `agent_runs.context_at`: the position in `prompt` where the two sections go. `NULL` means nothing is waiting | A boolean flag: the sections would land after the "## Answer" note of a fresh session |
| When the fill runs | In every `dispatch_pending`, also when no runner is connected | Only when a runner is connected: a runner coming back to many queued runs would wait for all of them at once |
| Who waits | The caller of the dispatch waits as long as today (up to about 10 s), without row locks | A background task: it changes what about 25 dispatch callers and many tests can assume |

Two small changes in the prompt follow from this:

- The two sections move from before the other context sections ("Answers from other projects", "Other projects you can ask", "Earlier rounds", …) to after them. They stay before the "## Answer / Rejection / Reminder" note and before what `_send_start` appends.
- When the prompt is near the 60,000 character limit, Memory and then Knowledge Base are the first sections left out. Today they are the last of the optional sections to go. The resume note now gets its room before they do.

## Architecture

**`backend/app/workflow/context.py`**
- New list `late_providers`: providers that may call an AI provider. They must only read.
- New `late_sections(db, task, role) -> list[str]`: runs them through the existing `_provided` (a failing provider is logged and skipped).
- `build_prompt` is unchanged: it still runs `context_providers`, which no longer holds the two slow ones.

**`backend/app/kb/context.py`, `backend/app/memory/context.py`**: `register()` appends to `late_providers` (Knowledge Base first, as today).

**`backend/app/workflow/engine.py`, `enqueue`**: sets `context_at = len(prompt)` right after `build_prompt`, before the resume note is appended. The lock order comment gets a line about the fill.

**New `backend/app/agent_runs/late_context.py`, `fill_pending(owner_id)`**
1. Lists the owner's queued runs with `context_at` set, oldest first.
2. For each run, in a session of its own that only reads: loads the run and its task and calls `late_sections`.
3. Inserts the sections at `context_at`, in order, while the prompt stays within `MAX_PROMPT_CHARS`. A section that does not fit is left out, with those after it.
4. Writes with one statement: `UPDATE agent_runs SET prompt = …, context_at = NULL WHERE id = … AND status = 'queued' AND context_at IS NOT NULL`, then commits. This takes only the run row lock, for the length of the statement, which fits the lock order (lock 3 alone).

**`backend/app/agent_runs/service.py`**
- `dispatch_pending` calls `fill_pending(owner_id)` first.
- `_claim_next` skips runs whose `context_at` is set, so a run is never sent before its fill.

No caller of `enqueue` or of the dispatch functions changes.

## Data and interfaces

- `agent_runs.context_at INTEGER NULL`, one migration made with `backend/scripts/makemigration.sh`. No backfill: existing runs have `NULL`, meaning their prompt is complete.
- Answering, draft and cron runs never set it.
- No change to the runner protocol or the API.

## Error handling and edge cases

- **Provider slow or failing**: the existing 5 s timeouts and fallbacks stay. The run goes out with keyword matches only, or without the section.
- **The fill itself fails** (any exception): it is logged and `context_at` is cleared. A run is never stuck because of optional context.
- **Crash between commit and fill**: the mark is in the DB. The next `dispatch_pending` for that owner fills it (a run ending, a request, the runner connecting).
- **Two dispatches at once**: both may build the sections. The conditional update lets one win. The other changes nothing.
- **Run cancelled or task deleted during the fill**: the update matches no row.
- **Task text edited between enqueue and fill**: the search uses the newer text.
- **Resumed sessions**: the full prompt is still filled, as today, since the runner falls back to it when the session cannot be resumed.

## Testing

Backend tests, written first.

- **Acceptance** (pattern of `tests/a2a/test_followups.py`): `ai.embed` is replaced by one that, while it is called, opens another session with `lock_timeout = 200ms`, locks the task row, the workflow row, the ended run and the new run, and posts a comment to the agent through the API. Driven once through `finish_run` (a run ends, the next is queued) and once through an HTTP caller (approving a document). All probes must succeed.
- `enqueue` calls no late provider and sets `context_at`.
- `fill_pending`: sections land at the mark and before a resume note; the mark is cleared; sections that do not fit are left out, last first; a failing provider or a failing fill still clears the mark; a cancelled run is not changed.
- `_claim_next` skips a marked run; `dispatch_pending` fills, then sends, and the `run_start` prompt holds both sections.
- A queued run left marked (as after a crash) is filled and sent on the next dispatch.
- Migration: up, down, up on a scratch DB, single alembic head.
- Updated: the tests in `tests/kb/test_context.py`, `tests/kb/test_review_fixes.py` and `tests/memory/test_context.py` that expect the two providers in `context_providers` or their sections in `build_prompt`'s result.
- Regression: `tests/workflow`, `tests/mcp`, `tests/agent_runs`, `tests/runner`, `tests/kb`, `tests/memory`.

## Out of scope

- Moving the wait off the caller. A request or the runner's message worker still waits for the embedding calls before its dispatch returns.
- One embedding call for both sections (today the same query text is embedded twice).
- Storing a query vector per task (approach B).
- Prompts of answering, Knowledge Base draft and cron runs: they do not use `build_prompt`.
- The fill's own session still holds one pooled connection, without row locks, while the provider is called.