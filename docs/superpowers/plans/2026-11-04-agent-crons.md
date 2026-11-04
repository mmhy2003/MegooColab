# Agent Crons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project's managers schedule prompts that one of the project's agents runs at each due time, exactly once. Each run runs commands in a throwaway copy of the code and leaves a report, and, as its cron allows, opens tasks or rewrites one Knowledge Base document.

**Architecture:**
- **Storage:** a new `app/crons` package holds `Cron`, its `CronRun`s (one per scheduled time, unique, so the claim is exactly once), schedule parsing and wording, a scheduler loop, and the cron run kind. That run kind is an `AgentRun` with `cron_run_id`: a fourth run target beside task, question and draft.
- **Reports:** the agent reports through a new MCP tool, `submit_cron_report`. The server opens the tasks, adds the comments and saves the document the report asks for, within the cron's mode.
- **Runner:** gains `crons/1`. A cron run works in a per-cron worktree, fetched and reset to the project's default branch before each run, run with the `workspace` policy, and reset again after.
- **Pages:** a new **Crons** tab on each project.

**Tech Stack:** FastAPI, async SQLAlchemy, Alembic, `croniter` and `cron-descriptor` (new backend dependencies), MCP server; Go runner; Next.js 16, React 19, TanStack Query, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-04-agent-crons-design.md`

## Global Constraints

- **Limits:**
  - name 1–100 characters;
  - prompt 1–20,000 characters;
  - schedule: five fields; numbers, `*`, `a-b`, `a,b`, `*/n`, `a-b/n`, and `MON`…`SUN`, `JAN`…`DEC`;
  - no seconds field, no `@` macros.
- **Too frequent:** a schedule with any two of its next 20 occurrences less than 5 minutes apart is refused with 422 `schedule_too_frequent`. An invalid one gives 422 `schedule_invalid`, with a plain-English `message`.
- **Time zone:** an IANA name, defaulting to the creator's browser zone.
- **Exactly once:** one `CronRun` row per `(cron_id, scheduled_at)` (unique). A scheduled time is started only by the process that inserted its row.
- **Skip rules:**
  - The previous run is still queued or running → the run is skipped, `skip_reason="previous_running"`.
  - Missed by more than 1 hour → one skipped row for the latest missed time (`"missed"`), and no run.
  - No usable agent: either none can work on the project (`"no_agent"`), or the run waited 15 minutes after its scheduled time while still queued (`"no_agent_online"`).
- **Time limit:** a cron run is cancelled after 30 minutes, and the report says so (`timed_out`).
- **Runs:**
  - `policy = workspace`, in a throwaway per-cron worktree reset to `origin/<default branch>`;
  - a run whose `git_after.head` differs from `git_before.head` is marked failed with `"made_a_commit"`;
  - a fetch failure runs on the last fetched commit, and the report says which (`commit`).
- **Modes:** `report` | `tasks` | `kb`.
  - **`tasks`:** at most 5 new tasks per run, each labelled `from cron`, with the run's link in its description. A finding with `existing_task_key` adds a comment instead.
  - **`kb`:** one document, created at the top of the project's space and titled `kb_title or cron.name`, then followed by id and recreated if deleted. Each run saves the whole new body as a revision credited to the agent's owner with the agent, summary `Cron: <name>`.
- **Notifications** (`Kind.needs_you`) go to the cron's creator, if they can still read the project, and the project's managers. Flags:
  - `notify_findings`, default true;
  - `notify_every`, default false;
  - `notify_failures`, default true.
- **Permissions:** managers and admins create, edit, pause, resume, delete and **Run now**. Members read the crons, their runs and reports. A chosen agent is checked with `can_use_agent` when the cron is saved.
- **Runner capability:** `crons/1` (backend `CRONS_CAPABILITY`, runner `CapabilityCrons`).
- **Methodology:** key `cron`, in a new group `crons`, labelled "Crons" in Admin › Methodology.
- **Copy:**
  - "Every day at 02:00" style descriptions come from `cron-descriptor`, in 24-hour time.
  - Skip texts: "skipped: the previous run was still going", "skipped: MegooColab was down at that time", "skipped: no agent online", "skipped: no agent can work on this project".
- **Housekeeping:** migrations only against `megoo_migrate`; never two pytest runs at once; no Prettier; `npm run gen:api` after schema changes; commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; no version bumps.

## Review Focus

1. **Two backend processes ticking at the same moment:** exactly one `CronRun` and one `AgentRun` per scheduled time. Pinned in Task 3.
2. **Daylight-saving changes in the cron's zone:**
   - a 02:30 schedule on the spring-forward day is skipped that day;
   - on the fall-back day it runs once.

   Pinned in Task 1.
3. **The cron's chosen agent deleted, unbound, or its owner removed from the project:** the run is skipped with `"no_agent"` and the managers are notified. It is never sent to another agent silently. Pinned in Task 3.
4. **A report naming more than 5 new tasks, or an `existing_task_key` from another project:** only 5 are created, and a foreign key is ignored (noted in the report). Pinned in Task 4.
5. **The agent pushes or commits:** the run is marked failed `"made_a_commit"`, and the worktree is reset before the next run. A push to a remote cannot be undone, so the methodology forbids it and the report shows the failure. Pinned in Task 5 and Task 3.

---

### Task 1: Schedules: validate, describe, next times, and the preview endpoint

**Files:**
- Modify: `backend/pyproject.toml` and `uv.lock` (`uv add croniter cron-descriptor`)
- Create: `backend/app/crons/__init__.py`, `backend/app/crons/schedule.py`, `backend/app/crons/router.py` (preview route only for now)
- Modify: `backend/app/main.py` (router)
- Test: `backend/tests/crons/__init__.py`, `backend/tests/crons/test_schedule.py`

**Interfaces:**
- Produces:
  - `schedule.check(expr: str, tz: str) -> None`:
    - raises `HTTPException(422, {"code": "schedule_invalid", "message": <plain English>})`, `"schedule_too_frequent"`, or `"timezone_invalid"`;
    - messages name the field: "Hour must be 0–23 (you wrote 25)", "Minute must be 0–59…", "Use five fields: minute, hour, day of month, month, day of week".
  - `schedule.describe(expr: str) -> str`, for example "Every day at 02:00" or "At 16:00, only on Friday", from `cron-descriptor` with `use_24hour_time_format=True`.
  - `schedule.next_times(expr: str, tz: str, after: datetime, n: int) -> list[datetime]` returns UTC times. On DST changes: a nonexistent local time is skipped, an ambiguous one occurs once.
  - `POST /api/crons/preview` with body `{schedule, timezone}` → `{ok: bool, error: str|None, description: str|None, next: list[datetime]}`, giving the next 3 times. It never fails with 422; the error is in the body. Any signed-in user may call it.

- [ ] **Step 1: Write the failing tests**
  - `test_valid_expressions_pass` for `"0 2 * * *"`, `"0 16 * * FRI"`, `"*/15 9-17 * * MON-FRI"` and `"0 0 1 * *"`.
  - `test_invalid_expressions_name_the_field`:
    - `"0 25 * * *"` → message contains "Hour must be 0–23";
    - `"0 2 * *"` → "Use five fields";
    - `"@daily"` → invalid.
  - `test_too_frequent`: `"* * * * *"` and `"*/2 * * * *"` give `schedule_too_frequent`; `"*/5 * * * *"` passes.
  - `test_describe`: `"0 2 * * *"` → `"At 02:00"` or `"Every day at 02:00"`. Pin whichever wording the library gives, and render the UI from it.
  - `test_next_times_in_zone`: Africa/Cairo `"0 2 * * *"` after 2026-11-04T10:00Z → the first time is 2026-11-05T00:00Z (UTC+2).
  - `test_dst_spring_forward_skips_and_fall_back_runs_once`, in Europe/Berlin:
    - `"30 2 * * *"` over 2026-03-29 has no time on that day;
    - over 2026-10-25 it has exactly one.
  - `test_preview_endpoint` returns `ok=False` with the message for a bad expression, and 3 next times for a good one.
- [ ] **Step 2: Run and see them fail.**
  - Run: `cd backend && uv run pytest tests/crons/test_schedule.py -q`
  - Expected: FAIL (import error).
- [ ] **Step 3: Implement.** Field checks come before `croniter` for the plain messages. `croniter` with a tz-aware start gives the next times. Check DST behaviour against the tests, and adjust the iteration (skip nonexistent, dedupe ambiguous) if the library differs.
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `uv run pytest tests/crons -q`
  - Expected: pass.
- [ ] **Step 5: Commit** `feat(crons): cron schedules — validate, describe, next times`.

### Task 2: Crons and their runs: tables and the CRUD API

**Files:**
- Create: `backend/app/crons/models.py`, `schemas.py`, `service.py`
- Modify:
  - `backend/app/crons/router.py`;
  - `backend/app/models.py`;
  - `backend/app/agent_runs/models.py` (`cron_run_id`; the check constraint becomes "exactly one of task, question, draft, cron_run");
  - the migration `<rev>_crons.py`.
- Test: `backend/tests/crons/test_api.py`

**Interfaces:**
- Produces:
  - **`Cron`:**
    - `id`, `project_id` (FK CASCADE), `name`, `prompt`, `schedule`, `timezone`;
    - `agent_id` (FK agents SET NULL, nullable: "any free agent");
    - `mode` String(10);
    - `kb_document_id` (FK kb_documents SET NULL, nullable), `kb_title` (nullable);
    - `notify_findings`, `notify_every`, `notify_failures`;
    - `paused`;
    - `created_by` (FK users SET NULL), `created_at`, `updated_at`;
    - `next_run_at` (nullable while paused), indexed.
  - **`CronRun`:**
    - `id`, `cron_id` (FK CASCADE), `scheduled_at`;
    - `status`: `queued` | `running` | `done` | `failed` | `skipped`;
    - `skip_reason` (nullable), `agent_run_id` (FK agent_runs SET NULL, nullable);
    - `report` JSONB (nullable), `commit` String(64) (nullable), `tasks_created` int, default 0;
    - `started_at`, `finished_at`;
    - unique `(cron_id, scheduled_at)`, index `(cron_id, scheduled_at desc)`.
  - **`AgentRun.cron_run_id`** (FK cron_runs CASCADE, nullable, indexed).
  - **Routes:**
    - `GET /api/projects/{ref}/crons` → `list[CronOut]` (members). `CronOut` is every field above plus:
      - `description` (from `schedule.describe`);
      - `next_run_at`;
      - `last_run: CronRunOut | None`;
      - `agent: Named | None`.
    - `POST /api/projects/{ref}/crons` with `CronIn` → 201. Managers only. It checks the schedule, and the agent with `is_usable_binding` plus `can_use_agent`, then sets `next_run_at`.
    - `GET /api/projects/{ref}/crons/{id}` → `CronOut`.
    - `PATCH /api/projects/{ref}/crons/{id}` with `CronPatch`. A changed schedule or zone recomputes `next_run_at`.
    - `DELETE /api/projects/{ref}/crons/{id}` → 204.
    - `POST /api/projects/{ref}/crons/{id}/pause` and `/resume`. Resume sets `next_run_at` from now, never in the past.
    - `GET /api/projects/{ref}/crons/{id}/runs?limit=50` → `list[CronRunOut]`. `CronRunOut` has id, scheduled_at, status, skip_reason, `agent: Named | None`, started_at, finished_at, report, commit, tasks_created.
    - `GET /api/projects/{ref}/crons/{id}/runs/{run_id}` → `CronRunOut`.
  - **Audit:** `cron.created`, `cron.updated`, `cron.deleted`, `cron.paused`, `cron.resumed`.

- [ ] **Step 1: Write the failing tests**
  - `test_managers_write_members_read` (the same shape as the Secrets project test).
  - `test_bad_schedule_is_refused` (422 `schedule_invalid`).
  - `test_chosen_agent_must_be_usable`: an unbound agent, or one the manager can't use, gives 422 `agent_not_available`.
  - `test_next_run_at_is_set_and_follows_edits_and_pause`:
    - create → `next_run_at` is the next time;
    - pause → null;
    - resume → in the future;
    - a schedule edit recomputes it.
  - `test_run_target_is_exactly_one` (an AgentRun with both a task and a cron run fails).
  - `test_list_shows_description_and_last_run`.
- [ ] **Step 2: Run and see them fail.**
  - Run: `uv run pytest tests/crons/test_api.py -q`
  - Expected: FAIL.
- [ ] **Step 3: Implement.** Generate the migration against `megoo_migrate`, and hand-edit `agent_runs_target_check` as in the Knowledge Base drafts migration.
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `uv run pytest tests/crons tests/kb_drafts/test_models.py tests/a2a/test_models.py -q`
  - Expected: pass.
- [ ] **Step 5:** Run `npm run gen:api`, then **commit** `feat(crons): crons and their runs`.

### Task 3: The scheduler and the cron run kind

**Files:**
- Create: `backend/app/crons/scheduler.py`, `backend/app/crons/turns.py`, `backend/app/workflow/methodology_texts/defaults/cron.md`
- Modify:
  - `backend/app/workflow/methodology.py` (`OTHER_KEYS["crons"] = ["cron"]`) and `methodology_history.py`;
  - `backend/app/main.py` (start and stop the loop, like `route_loop`);
  - `backend/app/agent_runs/service.py`:
    - `_claim_next` gates cron runs on `CRONS_CAPABILITY`, one running run per cron run;
    - `_send_start` → `_send_cron_start` via `_send_targeted_start`;
    - `_transition` → `crons.turns.on_run_finished`;
    - `cancel_run` allows managers;
    - lock the cron run (and its cron) before the run, like `_lock_draft_of`;
  - `backend/app/runner/registry.py` (`CRONS_CAPABILITY = "crons/1"`);
  - `backend/app/runner/protocol.py` (`RunCron{id, branch}`, `RunStart.cron: RunCron | None`);
  - `backend/app/secrets/delivery.py` (`_project_id` covers cron runs);
  - `backend/app/crons/router.py` (`POST …/crons/{id}/run-now` → `CronRunOut`, 201);
  - `backend/tests/workflow/test_methodology.py` and `tests/runner/test_protocol_v2.py` counts.
- Test: `backend/tests/crons/test_scheduler.py`, `test_turns.py`

**Interfaces:**
- Consumes: Task 1 `next_times`, Task 2 models.
- Produces:
  - **`scheduler.tick(now: datetime) -> None`**, run every 30 s by `cron_loop(stop)`. In its own sessions:
    - **(a) Due crons:** lock active crons with `next_run_at <= now` `FOR UPDATE SKIP LOCKED`. For each:
      - if `now - next_run_at > 1h`: insert one skipped `missed` row for the latest due time;
      - else insert a `CronRun(scheduled_at=next_run_at)` with `ON CONFLICT DO NOTHING`. Only an inserted row continues, to `start_run`.

      Then set `next_run_at` to the first time after `now`.
    - **(b) Queued too long:** cron runs still queued 15 minutes after `scheduled_at` → cancel the AgentRun and mark skipped `no_agent_online`.
    - **(c) Running too long:** cron runs running for more than 30 minutes → `cancel_run`. On finish the report gets `"timed_out": true`, and the status is failed.
  - **`scheduler.start_run(db, cron, cron_run) -> None`:**
    - skips `previous_running` when another run of the cron is queued or running;
    - picks the agent: the chosen one if usable, else any free usable agent with `crons/1`, online first, then least busy;
    - with no agent, skips `no_agent` and notifies the managers;
    - otherwise enqueues `AgentRun(cron_run_id=, policy=workspace, prompt=turns.cron_prompt(...), methodology_version_id=)` and adds the owner to the dispatch set.
  - **`turns.cron_prompt(db, cron, cron_run) -> tuple[str, MethodologyVersion]`:** the `cron` methodology text, then:
    - the project's name and key;
    - this run's and the previous run's times;
    - the previous run's report (as untrusted data);
    - the cron's prompt;
    - its mode's instructions:
      - report: report only;
      - tasks: "up to 5 new tasks; check open tasks with list_tasks first";
      - kb: "your report's document_md replaces the whole document".
  - **`turns.start_fields(db, run) -> (RunTask, str, dict)`:**
    - `RunTask(key=f"CRN-{cron.id.hex[:12]}", title=cron.name, project_key=project.key)`;
    - the binding's `local_path`;
    - fields: `role="cron"`, `mcp`, and `cron=RunCron(id=cron.id, branch=<first repository's default_branch or "main">)`;
    - raises `NotSupported` like drafts.
  - **`turns.on_run_finished(db, run)`** sets the CronRun's status:
    - `done` when the report was submitted;
    - `failed` with the run's reason when it failed or was cancelled, `timed_out` if the time limit stopped it;
    - `failed` with `"made_a_commit"` when `git_before.head != git_after.head`;
    - also `commit = git_before.head` and `finished_at`.

    It then sends notifications per the flags (Task 4 adds the findings case).
  - The draft-style per-run lock order: cron run row, then agent run.

- [ ] **Step 1: Write the failing tests** (with the fake connection helpers from `tests/agent_runs/test_dispatch.py`):
  - `test_one_run_per_scheduled_time_even_with_two_ticks`: `asyncio.gather(tick(now), tick(now))` gives one CronRun and one AgentRun.
  - `test_previous_run_still_going_skips`.
  - `test_missed_by_more_than_an_hour_records_one_skip_and_no_run`.
  - `test_queued_for_15_minutes_is_skipped_no_agent_online`.
  - `test_running_over_30_minutes_is_cancelled_and_marked_timed_out`.
  - `test_chosen_agent_gone_skips_no_agent_and_tells_managers`.
  - `test_any_free_agent_prefers_online_and_needs_crons_capability`.
  - `test_run_start_carries_cron_branch_and_workspace_policy`: the `run_start` has `cron.branch == "main"`, `policy == "workspace"` and `task.key == "CRN-…"`, and the project's secrets reach it (with `secrets/1` on the connection).
  - `test_a_commit_fails_the_run`: `finish_run` with `git_before.head != git_after.head` gives status failed and reason `made_a_commit`.
  - `test_run_now_starts_one_and_respects_a_running_one`.
  - `test_methodology_has_cron_in_the_crons_group`.
- [ ] **Step 2: Run and see them fail.**
  - Run: `uv run pytest tests/crons -q`
  - Expected: FAIL.
- [ ] **Step 3: Implement.** The `cron.md` text tells the agent:
  - work only in this throwaway copy; never commit, push, tag or change remotes;
  - run whatever commands the job needs;
  - use the secrets by name;
  - check open tasks before proposing new ones;
  - call `submit_cron_report` exactly once at the end;
  - include the untrusted-content paragraph.

  Add its hash to `DEFAULT_HISTORY`.
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `uv run pytest tests/crons tests/agent_runs tests/a2a tests/kb_drafts tests/secrets tests/workflow/test_methodology.py tests/runner -q -n 8`
  - Expected: pass.
- [ ] **Step 5:** Run `npm run gen:api`, then **commit** `feat(crons): the scheduler and cron runs`.

### Task 4: The cron report: MCP tool, tasks, Knowledge Base, notifications

**Files:**
- Create: `backend/app/mcp_server/cron_tools.py`
- Modify:
  - `backend/app/mcp_server/server.py` (register);
  - `backend/app/mcp_server/auth.py` (`require_run_task` lets a cron run read its own project's tasks: `list_tasks` and `get_task` only);
  - `backend/app/mcp_server/kb_tools.py` (cron runs may search, list and read, never `kb_write`);
  - `backend/app/mcp_server/a2a_tools.py` (cron runs refused);
  - `backend/app/crons/turns.py` (`apply_report`).
- Test: `backend/tests/crons/test_report.py`

**Interfaces:**
- Produces:
  - **`submit_cron_report(summary: str, findings: list[{title, detail, new_task?: bool, existing_task_key?: str}], checked: str = "", nothing_new: bool = False, document_md: str | None = None)`:** for the run's own cron run only. A second call gives `already_submitted`. It calls `turns.apply_report(db, run, ...)`:
    - stores the `report` (summary, findings with `task_key` filled in, checked, nothing_new, plus notes such as "3 more tasks not created: the limit is 5 per run");
    - **in `tasks` mode:**
      - creates up to 5 tasks for `new_task` findings in the project's first backlog column, as the agent's owner, with the `from cron` label (created if missing) and a description ending "From cron <name>: <link to the run>";
      - adds a comment with the run's link to each valid `existing_task_key` in the same project. A foreign key is ignored and noted;
    - **in `kb` mode:** writes `document_md` to the cron's document, created or recreated as Global Constraints say;
    - sets `tasks_created`.
  - **Notifications at finish:** when the report has findings, `notify_findings` sends "Cron <name>: <n> findings". Also "Cron <name> ran", and "Cron <name> failed/skipped" per the flags. Each links to `/projects/<KEY>/crons/<id>?run=<run_id>`.

- [ ] **Step 1: Write the failing tests**
  - `test_report_only_mode_creates_nothing`.
  - `test_tasks_mode_creates_at_most_five_labelled_tasks`: 7 findings with `new_task` → 5 tasks with the label `from cron` and a note about the 2 left.
  - `test_existing_task_gets_a_comment_and_foreign_keys_are_ignored`.
  - `test_kb_mode_writes_one_document_and_recreates_it`: first run creates the document and a second run adds revision 2 (summary `Cron: <name>`). After the document is deleted, the next run creates a new one and the cron follows its id.
  - `test_cron_run_reads_only_its_project_tasks`: `list_tasks("PAY")` works, `list_tasks("WEB")` and `kb_write` and `ask_project` give `not_allowed_in_role`.
  - `test_findings_notify_creator_and_managers`, plus a no-findings run with `notify_every=False` notifies no one.
- [ ] **Step 2: Run and see them fail.**
  - Run: `uv run pytest tests/crons/test_report.py -q`
  - Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `uv run pytest tests/crons tests/mcp -q -n 8`
  - Expected: pass. Then run the whole backend suite (`uv run pytest -q -n auto`) alone.
- [ ] **Step 5: Commit** `feat(crons): the cron report — tasks, Knowledge Base, notifications`.

### Task 5: Runner: the cron's throwaway copy

**Files:**
- Modify:
  - `runner/internal/protocol/protocol.go` (`RunCron{ID, Branch}`, `RunStart.Cron *RunCron \`json:"cron,omitempty"\``, `CapabilityCrons = "crons/1"` in `NewHello`, and the capability-list tests);
  - `runner/internal/drafts/drafts.go` (generalise: `EnsureAt(ctx, root, cacheRoot, agentID, id, repo string)` with root `"drafts"` or `"crons"`, and `RemoveAt`/`SweepAt` likewise; `Ensure`/`Remove`/`Sweep` keep their signatures as wrappers);
  - `runner/internal/startbranch/startbranch.go` (export `StartPoint`);
  - `runner/internal/jobs/manager.go` (`drive`: a cron run takes the drafts-style branch with root `"crons"`, then refreshes).
- Test: `runner/internal/jobs/crons_test.go`

**Interfaces:**
- Produces, for a cron run in `drive`:
  - **The worktree:** `drafts.EnsureAt(ctx, "crons", …, cronID, repo)`.
  - **Refreshing it:**
    - `point, err := startbranch.StartPoint(ctx, logf, repo, origin, rs.Cron.Branch)` fetches, or falls back to the last fetched copy;
    - `git -C wt checkout --detach --force <point>` and `git -C wt clean -fdx`;
    - `run_finished.git_before` is the state then (its head is the commit used).
  - **Policy:** the run's own (`workspace`).
  - **After the agent:** `git_after` is captured (so the server sees a commit), then the worktree is reset to `git_before.head` and cleaned.
  - **Never `git push`:** the runner does nothing more; the methodology forbids it.
  - **Removal:** a cron's folder goes on the 30-day sweep under `crons/`.

- [ ] **Step 1: Write the failing tests**
  - `TestCronRunWorksOnTheDefaultBranchInItsOwnWorktree`: a repo with an `origin` (a bare clone) whose `main` moved ahead. The run's `git_before.head` is origin's new head, and `Cwd` is under `crons/agent-1/`.
  - `TestCronRunChangesAreThrownAway`: the scenario writes a file. After the run the file is gone, and the next run starts clean.
  - `TestCronRunCommitIsReported`: the scenario commits, so `git_after.head != git_before.head`.
  - `TestCronFetchFailureUsesTheLastFetchedCommit`.
  - `TestHelloAdvertisesCrons`.
- [ ] **Step 2: Run and see them fail.**
  - Run: `cd runner && go test ./internal/jobs/ ./internal/drafts/ ./internal/protocol/ ./internal/conn/`
  - Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `go test ./...`
  - Expected: ok. Known timing-flaky tests (`TestSteerAfterTurnEnds…`, `TestMessageCoalescing`) are rerun alone if they fail.
- [ ] **Step 5: Commit** `feat(runner): cron runs in a throwaway copy of the default branch`.

### Task 6: Frontend: the Crons tab, the schedule helper, history and reports

**Files:**
- Create:
  - `frontend/src/lib/crons.ts`;
  - `frontend/src/components/crons/CronList.tsx`, `CronEditor.tsx`, `ScheduleField.tsx`, `CronRuns.tsx`, `CronReport.tsx`;
  - `frontend/src/app/(app)/projects/[key]/crons/page.tsx` and `[cronId]/page.tsx`.
- Modify:
  - `frontend/src/app/(app)/projects/[key]/layout.tsx` (a "Crons" tab after "Chats");
  - `frontend/src/components/workflow/MethodologyEditor.tsx` (`METHODOLOGY_STAGES` gains `"crons"`, card `{id: "crons", label: "Crons", keys: ["cron"]}`);
  - `frontend/src/lib/errors.ts` (`schedule_*`, `timezone_invalid`).
- Test: `frontend/src/components/crons/__tests__/ScheduleField.test.tsx`, `CronList.test.tsx`, `CronEditor.test.tsx`, `CronRuns.test.tsx`, plus the layout's tab test and `MethodologyEditor.test.tsx`

**Interfaces:**
- Consumes: Task 1 preview, Task 2 and 3 routes.
- Produces:
  - **`ScheduleField({ value, timezone, onChange, onValid })`:**
    - **Presets** set the expression: Every hour `0 * * * *`; Every day at… `0 9 * * *`; Weekdays at… `0 9 * * 1-5`; Every Monday at… `0 9 * * 1`; 1st of the month `0 9 1 * *`; Custom (focuses the input). The "at…" presets show a time input that rewrites the minute and hour fields.
    - **The field boxes:** below the input, five labelled boxes (minute, hour, day of month, month, day of week).
    - **Preview:** `POST /api/crons/preview`, debounced 300 ms. The description shows in a green box with the zone, plus "Next runs: …" (3 times, in the zone). An error shows in pink, and `onValid(false)`.
  - **`CronEditor`** (dialog, new or edit):
    - fields: Name, the prompt ("What the agent should do"), `ScheduleField`, Time zone (a select of `Intl.supportedValuesOf("timeZone")`, defaulting to the browser's), Agent ("Any free agent of <KEY>" plus the agents from `useProjectAgents`);
    - **"What it may do with what it finds":** three radio cards with the mockup's copy. The Knowledge Base option has a title field ("Each run rewrites this document");
    - **"Tell me":** three checkboxes;
    - buttons: **Save cron** (disabled until the schedule is valid), and **Run once now to try it** (shown when editing an existing cron).
  - **`CronList`:**
    - the mockup's table: name and the prompt's first line, When (description plus the expression), Next run, Last run (outcome text), Agent;
    - **Run now**, **Pause** and **Resume** for managers;
    - cards below `sm`;
    - **New cron** for managers.
  - **Cron page:** settings (**Edit**, **Delete**) with `CronRuns`, the history list, beside `CronReport`, the selected run (`?run=`):
    - the summary;
    - findings with task links (`PAY-88 created` or `PAY-61 (open)`);
    - what was checked;
    - the commit used;
    - skip and failure reasons in plain words.
  - **Methodology:** a "Crons" tab.
  - Fits 280 px.

- [ ] **Step 1: Write the failing tests:**
  - `ScheduleField`:
    - a preset fills `0 9 * * 1-5`;
    - typing `0 25 * * *` shows the server's message and calls `onValid(false)`;
    - a valid expression shows the description and 3 next runs.
  - `CronEditor` posts `{name, prompt, schedule, timezone, agent_id: null, mode: "tasks", notify_findings: true, notify_every: false, notify_failures: true}`, and Save is disabled while the schedule is invalid.
  - `CronList`:
    - shows the description, the expression and the last-run outcome;
    - members see no Run now, Pause or New cron;
    - Run now posts to `/run-now`.
  - `CronRuns` and `CronReport`:
    - a skipped run shows "skipped: no agent online";
    - a report shows its findings with links to `/projects/PAY/tasks/88`.
  - The project layout has a "Crons" tab, and the methodology editor has a "Crons" tab.
- [ ] **Step 2: Run and see them fail.**
  - Run: `cd frontend && npx vitest run src/components/crons src/components/workflow "src/app/(app)/projects"`
  - Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and see them pass.** Same command, then `npx tsc --noEmit`, `npm run lint` and `npm test`.
- [ ] **Step 5: Commit** `feat(crons): the Crons tab, schedule helper, history and reports`.

### Task 7: End-to-end

**Files:**
- Create: `frontend/e2e/crons.spec.ts`

- [ ] **Step 1: Write the spec**, following `secrets.spec.ts` for the setup (a project, the admin's agent bound to a repository that has an `origin`, and the runner):
  1. On Project › Crons, **New cron**:
     - type `0 25 * * *`, then see "Hour must be 0–23" and Save disabled;
     - pick the "Weekdays at…" preset and see the plain-words description and next runs;
     - name it "Nightly dependency check", choose "Report, and open tasks for real problems", and Save.
  2. **Run now.** The fake agent's turn (matched on the cron prompt) calls `submit_cron_report` with one finding with `new_task: true`.
  3. The cron page's history shows the run as done. The report shows the finding linked to the new task, and the task carries the `from cron` label.
  4. The run's `git_before.head` (shown as the commit used) equals origin's head.
  5. At 280 px the Crons tab and the cron page don't scroll sideways.
- [ ] **Step 2: Run it.**
  - Run: `SPECS="crons.spec.ts secrets.spec.ts kb-drafts.spec.ts" bash <scratchpad>/e2e-mobile.sh`
  - Expected: all pass.
- [ ] **Step 3: Commit** `test(crons): end-to-end cron from schedule to report and task`.
