# Agent Merge Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A merged pull request finishes its round even when the token can't read checks or reviews. Failing reads
show in words. A round waiting on an agent's merge stops looking like a person's job, unless confirming it fails.

**Architecture:**
- Provider reads treat a refused checks or reviews call as `unknown`.
- The PR row stores which extras were missing, as `limited`.
- A new `Needs.merge_confirmation` wait replaces `human_code_review` after an agent's merge, when MegooColab can
  confirm the merge itself. A per-read check escalates `merge_not_confirmed` when it can't.
- The frontend shows the read problems, the new wait and the new escalation.

**Tech Stack:**
- backend: FastAPI, SQLAlchemy async, Alembic, pytest, httpx MockTransport;
- frontend: Next.js, React, vitest, Playwright e2e with `frontend/e2e/helpers/fakeGit.ts`.

**Spec:** `docs/superpowers/specs/2026-11-05-agent-merge-confirmation-design.md` (approved; read it first).

## Global Constraints

- **Branch:** work on `fix/agent-merge-confirmation`, made from develop.
- **No version bump and no release notes.** Both wait for "release".
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **No Prettier.** Match the surrounding style by hand.
- **One pytest run at a time,** never two. Redirect long output to a file and read its tail.
- **Migrations:** generate them and run downgrade/upgrade only against `megoo_migrate`, using
  `DEV_DATABASE_URL=postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_migrate`. Never the dev DB.
- **Docker:** only the `megoo-e2e` compose project and the dev containers. Never touch cloudflared or the user's
  `megoocolab-*` containers.
- **Exact values from the spec:**
  - lasting errors: `forbidden`, `unauthorized`, `not_found`, `bad_token`, `url_mismatch`;
  - passing errors: `rate_limited`, `unreachable`, `bad_response`, `error`;
  - 3 failures in a row before a passing error escalates;
  - a 10-minute grace for `still_open`.
- **Copy from the spec, verbatim:**
  - "checks unknown";
  - "review unknown";
  - "The agent merged the pull request, but MegooColab couldn't confirm it.";
  - "GitHub still shows it open.";
  - "Agent merged · confirming";
  - "The agent merged the pull request. MegooColab finishes the round when GitHub shows the merge.";
  - "merging · PR #n" / "merging";
  - the reason table in spec §3.
- **The host's name** in user-facing text comes from `HOST_NAME[kind]`. Never hard-code "GitHub" where the host
  can be GitLab or Gitea.

## Review Focus

- **A round escalated `merge_not_confirmed` whose next read sees `merged`** must finish by itself, with no person
  involved. `apply_status` only calls `settle_done` when the state changed, so this depends on the row still
  saying `open`. The test is in Task 4.
- **A webhook arriving during `merge_confirmation`** (a review comment, a push) must not send a merged PR back to
  its agent. `send_back.consider` stays on `human_code_review` only. The test is in Task 3.
- **Resume after a pause during `merge_confirmation`** must not notify anyone, must rest on `merge_confirmation`,
  and must restart the 10-minute clock. The test is in Task 3.
- **The poll's exception path** (`jobs.pr_poll`, code `"error"`) counts toward the 3 passing failures too. The
  test is in Task 4.
- **A production fix (back-merge PR) after an agent's merge** stays on `human_code_review` and stays in Needs you.
  The test is in Task 3.

---

### Task 1: Tolerant provider reads

**Files:**
- Modify: `backend/app/git/providers.py`:
  - `PrStatus` (lines 50-56);
  - `_optional` (~176);
  - `_github` (~256-264);
  - `_gitea` (~267-272).
- Test: `backend/tests/git/test_providers.py`

**Interfaces:**
- Produces:
  - `PrStatus.limited: tuple[str, ...] = ()`, whose values are among `"checks"` and `"review"`, in that order;
  - `PrStatus.checks` / `.review` may be `"unknown"`.

- [ ] **Step 1: Write the failing tests** in `test_providers.py`, using the existing `_client(routes)` helper,
  where an `int` route value is that status code:

```python
async def test_github_refused_extras_are_unknown_and_the_state_still_reads():
    # routes as in test_github_status_mapping, with the PR merged; status -> 403, check-runs -> 403
    st = await providers.fetch_pr(conn, ref, client=_client(routes))
    assert (st.state, st.checks, st.review, st.limited) == ("merged", "unknown", "approved", ("checks",))
    routes[f"{base}/pulls/12/reviews"] = 403
    st = await providers.fetch_pr(conn, ref, client=_client(routes))
    assert (st.checks, st.review, st.limited) == ("unknown", "unknown", ("checks", "review"))

async def test_github_one_refused_checks_call_makes_checks_unknown():
    # status -> 200 success (total_count 1), check-runs -> 404
    assert (await providers.fetch_pr(conn, ref, client=_client(routes))).checks == "unknown"

async def test_github_a_refused_pull_request_still_fails_the_read():
    # pulls/12 -> 403
    with pytest.raises(GitProviderError) as e:
        await providers.fetch_pr(conn, ref, client=_client(routes))
    assert e.value.code == "forbidden"

async def test_github_other_errors_on_extras_still_fail_the_read():
    # check-runs -> 401 raises "unauthorized"; check-runs -> 403 with X-RateLimit-Remaining: 0 raises "rate_limited"

async def test_gitea_refused_extras_are_unknown():
    # Gitea routes as in test_gitea_status_mapping; status -> 403, reviews -> 404
    st = await providers.fetch_pr(conn, ref, client=_client(routes))
    assert (st.checks, st.review, st.limited) == ("unknown", "unknown", ("checks", "review"))
```

For the rate-limit case, extend `_client` so a route value can be an `httpx.Response`, returned as is. That's
needed for the header.

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && uv run pytest tests/git/test_providers.py -q > ../.superpowers/t1.txt 2>&1; tail -20 ../.superpowers/t1.txt`

Expected: the new tests FAIL. `limited` doesn't exist yet, or a `forbidden` is raised.

- [ ] **Step 3: Implement**

- Add `_extra(client, conn, path) -> Any | None`. It returns `None` when `_get` raises `forbidden` or
  `not_found`, and lets every other code through.
- Leave `_optional` as it is: GitLab approvals still tolerate only `not_found`.
- In `_github`, a `None` from either checks call makes `checks = "unknown"` and adds `"checks"` to `limited`.
- A `None` from reviews makes `review = "unknown"` and adds `"review"`.
- In `_gitea`, do the same for its status and reviews calls.
- Update the `PrStatus` field comments so the values include `unknown`.

- [ ] **Step 4: Run to see them pass,** plus the whole file.

Run: the Step 2 command.

Expected: all of `test_providers.py` PASSES, including the old `test_a_403_without_rate_limit_is_forbidden`,
which tests `_send` directly.

- [ ] **Step 5: Commit**

```bash
git add backend/app/git/providers.py backend/tests/git/test_providers.py
git commit -m "fix(git): a refused checks or reviews read no longer hides the pull request's state"
```

---

### Task 2: Store `limited`, and expose the read problem on the PR

**Files:**
- Modify:
  - `backend/app/git/models.py`: `TaskPullRequest`, adding a column `limited: Mapped[str | None] =
    mapped_column(String(30))` and comments that list `unknown`;
  - `backend/app/git/service.py`: `apply_status` stores `",".join(status.limited) or None`;
  - `backend/app/workflow/schemas.py`: `PullRequestOut`;
  - `backend/app/tasks/service.py`: `pull_requests_of`.
- Create: an Alembic migration `task_pull_request_limited`, generated with `scripts/makemigration.sh` against
  `megoo_migrate`.
- Test: `backend/tests/git/test_tracking.py`

**Interfaces:**
- Consumes: `PrStatus.limited` (Task 1).
- Produces:
  - `TaskPullRequest.limited: str | None`, e.g. `"checks"`, `"review"` or `"checks,review"`;
  - `PullRequestOut.error: str | None`, which is never `"branch_mismatch"` (that one maps to `None`);
  - `PullRequestOut.limited: str | None`;
  - `PullRequestOut.host: GitKind | None`, the connection's kind, or `None` when untracked;
  - `PullRequestOut.next_check_at: datetime | None`, for "It tries again at <time>".

- [ ] **Step 1: Write the failing tests** in `test_tracking.py`, reusing its existing world helpers:
  - `test_a_partial_read_stores_limited_and_counts_as_a_success`: give the row `failures=4` and `error="forbidden"`
    first. Then `apply_status` with `limited=("checks",)` → `row.limited == "checks"`, `row.failures == 0`,
    `row.error is None`.
  - `test_a_full_read_clears_limited`.
  - `test_a_merged_partial_read_finishes_the_waiting_round`: a workflow on `human_code_review`; `apply_status`
    with `state="merged"`, `checks="unknown"` and `limited=("checks",)` → the workflow is `finished`.
  - `test_the_workflow_api_shows_the_read_problem`: a row with `error="forbidden"` →
    `GET /api/tasks/{key}/workflow` gives `pull_request.error == "forbidden"`, `pull_request.host == "github"`
    and `next_check_at` set. A row with `error="branch_mismatch"` gives `error is None`.

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && uv run pytest tests/git/test_tracking.py -q > ../.superpowers/t2.txt 2>&1; tail -20 ../.superpowers/t2.txt`

Expected: FAIL. There's no `limited` attribute or field yet.

- [ ] **Step 3: Implement**

- Generate the migration against `megoo_migrate`, then check it with
  `alembic downgrade -1 && alembic upgrade head` there.
- In `pull_requests_of`, join `GitConnection.kind` with an outer join on `connection_id`.

- [ ] **Step 4: Run to see them pass,** then the git and workflow suites.

Run: `cd backend && uv run pytest tests/git tests/workflow tests/core/test_migrations.py -q > ../.superpowers/t2.txt 2>&1; tail -20 ../.superpowers/t2.txt`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/git/models.py backend/app/git/service.py backend/app/workflow/schemas.py backend/app/tasks/service.py backend/migrations/versions/*_task_pull_request_limited.py backend/tests/git/test_tracking.py
git commit -m "feat(git): remember what a pull request read couldn't see, and show read problems on the PR"
```

---

### Task 3: The `merge_confirmation` wait

**Files:**
- Modify:
  - `backend/app/workflow/models.py`:
    - `Needs`, adding `merge_confirmation = "merge_confirmation"`;
    - a module constant `MERGE_WAITS = frozenset({Needs.human_code_review, Needs.merge_confirmation})`.
  - `backend/app/git/agent_review.py`: a new `merge_wait`, and `rest_after_merge` used in `_handle_pr_review`.
  - `backend/app/git/service.py`: `settle_done` accepts `MERGE_WAITS`.
  - `backend/app/workflow/finish.py`: `approve_human_review` accepts `MERGE_WAITS`, via a new `mark_merged`.
  - `backend/app/workflow/engine.py`:
    - `NEEDS_TITLES[Needs.merge_confirmation] = "{key}: confirming the merge"`;
    - `_pending_need`;
    - `resume`, which doesn't notify for `merge_confirmation`.
  - `backend/app/chats/service.py`: lines ~56, 459, 486, 497 and 529 use `MERGE_WAITS`;
    `NEEDS_STATE[merge_confirmation] = "merging"`.
  - `backend/app/chats/schemas.py`: `ChatState`, adding `"merging"`.
  - `backend/app/dashboard/needs.py`: `_workflow_waits_query` leaves out `Needs.merge_confirmation`.
- Test: `backend/tests/git/test_agent_review.py`, `backend/tests/dashboard/` (the existing needs test file),
  `backend/tests/chats/` (the existing chat state and end tests).

**Interfaces:**
- Produces:
  - `MERGE_WAITS: frozenset[Needs]` in `app.workflow.models`;
  - `async def merge_wait(db, wf, task) -> Needs` in `app.git.agent_review`. It returns `Needs.merge_confirmation`
    only when there is no `wf.back_merge_pr_url`, and the main `TaskPullRequest` row exists with a non-null
    `connection_id` and `error != "branch_mismatch"`. Otherwise it returns `Needs.human_code_review`.
  - `async def rest_after_merge(db, wf, task) -> None` in `app.git.agent_review`:
    - it calls `wait_for(db, wf, await merge_wait(...), notify=False)`;
    - for `merge_confirmation`, it locks the main row and sets `failures = 0` and `next_check_at = now`.

    `failures` then counts only the failures since the wait began.
  - `async def mark_merged(db, wf, task, user) -> None` in `app.workflow.finish`: the event
    `human_review.approved`, the audit `workflow.human_review_approved` and `finish_workflow`, as
    `approve_human_review` does today. `approve_human_review` keeps its checks, then calls it.

- [ ] **Step 1: Write the failing tests.** Use `_agent_review`, `_end`, `_end_review` and `APPROVED` from
  `test_agent_review.py`:
  - `test_approved_and_merged_finishes_once_the_merge_is_seen`: change its first assertion to
    `("waiting_human", "merge_confirmation")`. The rest stands.
  - `test_an_agent_merge_rests_out_of_needs_you_without_a_notice`: after `APPROVED`, `GET /api/dashboard` (the
    owner's client) has no needs item for PAY-1, and no `Notification` mentions PAY-1's review.
  - `test_a_person_taking_over_still_waits_on_code_review`: escalate `agent_merge_failed`, then accept →
    `needs == "human_code_review"`, and the item is in Needs you.
  - `test_a_back_merge_pr_rests_on_code_review`: `wf.back_merge_pr_url` set before the review ends → `needs ==
    "human_code_review"`. Add the same assertion for an untracked main row (`connection_id=None`) and for
    `error="branch_mismatch"`.
  - `test_mark_merged_finishes_a_merge_confirmation`: `POST /api/tasks/PAY-1/workflow/human-review` with
    `{"approved": true}` → `finished`.
  - `test_a_changes_requested_webhook_during_merge_confirmation_is_ignored`: `send_back.consider` returns
    `"ignored:not_waiting"`.
  - `test_resume_after_a_pause_rests_on_merge_confirmation`: pause, then `resume` → `needs ==
    "merge_confirmation"`, a new `waiting_since`, and no new notification.
  - In the chats tests:
    - `test_ending_a_chat_leaves_a_merge_confirmation_alone`: the workflow isn't paused;
    - `test_chat_state_is_merging`: the chat's `state == "merging"`.

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && uv run pytest tests/git/test_agent_review.py tests/dashboard tests/chats -q > ../.superpowers/t3.txt 2>&1; tail -30 ../.superpowers/t3.txt`

Expected: the new and changed tests FAIL, on `needs == "human_code_review"` or a missing attribute.

- [ ] **Step 3: Implement**

- **The review handler:** in `_handle_pr_review`, replace `wait_for(db, wf, Needs.human_code_review,
  notify=False)` with `rest_after_merge`. The `settle_done` call right after it stays.
- **`_pending_need`:** in agent mode, when the last run is a `pr_review` whose `step_result` has `merged: True`,
  it returns `await merge_wait(...)`. Otherwise it returns `human_code_review`, as today.
- **`resume`:** passes `notify=False` for `merge_confirmation`. For that wait, it also resets the row the way
  `rest_after_merge` does: call `rest_after_merge` instead of `wait_for`.
- **Leave alone:** `send_back.consider`, `send_back`'s own waits and `finish._handle_finish`. They stay on
  `human_code_review` (Review Focus).

- [ ] **Step 4: Run to see them pass,** then the whole backend suite.

Run: `cd backend && uv run pytest -q -x > ../.superpowers/t3.txt 2>&1; tail -20 ../.superpowers/t3.txt`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "fix(workflow): an agent's merge waits quietly for confirmation instead of asking a person to review"
```

---

### Task 4: Escalate when the merge can't be confirmed

**Files:**
- Modify:
  - `backend/app/git/service.py`: `check_confirmation`; calls from `refresh_pr` and `apply_status`;
    `settle_done`, which also acts on an escalated `merge_not_confirmed`;
  - `backend/app/git/jobs.py`: `pr_poll`'s exception path also calls `check_confirmation`, in its own session;
  - `backend/app/workflow/engine.py`: `escalate(db, wf, reason, *, cause: str | None = None)`; the event data
    becomes `{"reason": reason}`, plus `{"cause": cause}` when set;
  - `backend/app/git/agent_review.py`: registers the `ACCEPT_HANDLERS` and `RETRY_HANDLERS` for
    `merge_not_confirmed`.
- Test: `backend/tests/git/test_merge_confirmation.py` (new)

**Interfaces:**
- Consumes: `MERGE_WAITS`, `rest_after_merge` and `mark_merged` (Task 3); `TaskPullRequest.error`, `failures` and
  `state`.
- Produces:
  - in `app.git.service`:
    - `LASTING_ERRORS = frozenset({"forbidden", "unauthorized", "not_found", "bad_token", "url_mismatch"})`;
    - `CONFIRM_FAILURES = 3`;
    - `CONFIRM_GRACE = timedelta(minutes=10)`;
    - `async def check_confirmation(db, task_id: uuid.UUID, kind: str) -> bool`.
  - `check_confirmation` takes the engine lock order (task, workflow, row) and acts only when the workflow is
    `waiting_human` / `merge_confirmation` and `kind == PR_MAIN`. It escalates `merge_not_confirmed` with `cause` set to:

    | Cause | When |
    |---|---|
    | `row.error` | `row.error` is in `LASTING_ERRORS` |
    | `row.error` | `row.error` is any other code except `branch_mismatch`, and `row.failures >= CONFIRM_FAILURES` |
    | `"branch_mismatch"` | `row.error == "branch_mismatch"` |
    | `"still_open"` | `row.error is None`, `row.state == "open"`, and `now - wf.waiting_since >= CONFIRM_GRACE` |

    It returns True when it escalated.

  - `ESCALATION` handlers:
    - accept calls `finish.mark_merged`;
    - retry clears `escalation_reason` as the other retry paths do, calls `rest_after_merge`, then
      `queue_refresh`. It never enqueues a run.

- [ ] **Step 1: Write the failing tests** in the new file. Build on `_agent_review` and `APPROVED` from
  `test_agent_review.py`, reaching `merge_confirmation` first. Patch `providers.fetch_pr` with `monkeypatch` to
  raise `GitProviderError(code)` or return a `PrStatus`. Drive reads through `service.refresh_pr`.
  - `test_a_lasting_error_escalates_on_the_first_failure`: parametrize over the five lasting codes. One failed
    read → `escalation_reason == "merge_not_confirmed"`, and the `workflow.escalated` event's `data["cause"] ==
    code`.
  - `test_a_passing_error_escalates_on_the_third_failure`: `unreachable` twice → still `merge_confirmation`; a
    third → escalated, with `cause` `unreachable`.
  - `test_the_poll_exception_path_counts`: with `refresh_pr` raising `RuntimeError` inside `jobs.pr_poll` three
    times (move `next_check_at` back each time) → escalated, with `cause` `error`.
  - `test_still_open_after_ten_minutes_escalates`: an open read at 9 minutes (`waiting_since` moved back) → still
    waiting; at 11 minutes → escalated, with `cause` `still_open`.
  - `test_old_failures_dont_count`: a row with `failures=28` before the review ends → one `unreachable` read
    doesn't escalate.
  - `test_a_merged_read_finishes_the_escalated_round`: escalated by `forbidden`, then a read returning `merged` →
    `finished`, and `needs is None`.
  - `test_a_closed_read_on_the_escalated_round_escalates_pr_closed`.
  - `test_accept_finishes_it`: `POST .../workflow/escalation {"action": "accept"}` → `finished`, with a
    `human_review.approved` event.
  - `test_retry_reads_again_and_runs_no_agent`: `{"action": "retry"}` → `needs == "merge_confirmation"`, a
    `git.pr_refresh` job queued, and no new `AgentRun`.
  - `test_human_review_mode_never_escalates_merge_not_confirmed`: a `human_code_review` wait plus a `forbidden`
    read → unchanged.

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && uv run pytest tests/git/test_merge_confirmation.py -q > ../.superpowers/t4.txt 2>&1; tail -30 ../.superpowers/t4.txt`

Expected: FAIL, because `check_confirmation` doesn't exist.

- [ ] **Step 3: Implement**

- **In `refresh_pr`:** after each `back_off` (`url_mismatch` and provider errors), and after `apply_status`, call
  `await check_confirmation(db, task_id, kind)`.
- **In `apply_status`:** keep the early `return` when nothing changed. `check_confirmation` runs from
  `refresh_pr`, so it runs whether or not the state changed.
- **In `settle_done`:** widen the guard to `wf.needs in MERGE_WAITS or (wf.needs == Needs.escalation and
  wf.escalation_reason == "merge_not_confirmed")`. Then check that `finish_workflow` leaves `needs` and
  `escalation_reason` cleared. Fix it if not.

- [ ] **Step 4: Run to see them pass,** then the whole backend suite.

Run: `cd backend && uv run pytest -q > ../.superpowers/t4.txt 2>&1; tail -20 ../.superpowers/t4.txt`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests/git/test_merge_confirmation.py
git commit -m "fix(git): escalate when an agent's merge can't be confirmed, and finish once it is"
```

---

### Task 5: Move the rounds already stuck

**Files:**
- Create: an Alembic migration `merge_confirmation_waits`, data only. Its `upgrade` executes the module constant
  `MOVE_SQL`; its `downgrade` sets those rows back to `human_code_review` with `DOWN_SQL`.
- Test: `backend/tests/workflow/test_merge_confirmation_migration.py` (new)

**Interfaces:**
- Consumes: `Needs.merge_confirmation` (Task 3).
- Produces: `MOVE_SQL: str`. It moves the workflows that match all of these:
  - `status = 'waiting_human'`, `needs = 'human_code_review'`, `stage = 'done'` and `finish_pr_review = 'agent'`;
  - `back_merge_pr_url IS NULL`;
  - a main `task_pull_requests` row with `connection_id IS NOT NULL` and `error IS DISTINCT FROM
    'branch_mismatch'`;
  - their latest `pr.agent_reviewed` task event has `data->>'merged' = 'true'`;
  - no `workflow.escalated` event comes after it.

  For each moved row it also sets `waiting_since = now()`, and on its main PR row `failures = 0` and
  `next_check_at = now()`.

- [ ] **Step 1: Write the failing test.** Load the migration module with `importlib`, globbing
  `migrations/versions/*_merge_confirmation_waits.py`. Seed five workflows:
  1. qualifying;
  2. human mode;
  3. agent mode, but escalated after the review;
  4. with a back-merge PR;
  5. with `merged: false`.

  `await db.execute(text(module.MOVE_SQL))`, then assert that only workflow 1 has `needs == "merge_confirmation"`,
  and that its PR row has `failures == 0`.

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && uv run pytest tests/workflow/test_merge_confirmation_migration.py -q > ../.superpowers/t5.txt 2>&1; tail -20 ../.superpowers/t5.txt`

Expected: FAIL, because the migration file doesn't exist yet.

- [ ] **Step 3: Write the migration.** Its `down_revision` is Task 2's migration. Check it against
  `megoo_migrate` with `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.

- [ ] **Step 4: Run to see it pass,** plus `tests/core/test_migrations.py`.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/*_merge_confirmation_waits.py backend/tests/workflow/test_merge_confirmation_migration.py
git commit -m "fix(workflow): move rounds already waiting on an agent's merge to the new wait"
```

---

### Task 6: Repository settings show pull request read problems

**Files:**
- Modify:
  - `backend/app/projects/schemas.py`: `RepoOut` gains `pr_error: str | None = None` and
    `pr_limited: str | None = None`;
  - `backend/app/projects/router.py`: `_repo_out` fills them;
  - `backend/app/git/service.py`: a new `repo_read_problem`.
- Test: `backend/tests/projects/test_projects.py`, or the existing repository API test file.

**Interfaces:**
- Produces: `async def repo_read_problem(db, repo: ProjectRepository, conn: GitConnection) -> tuple[str | None,
  str | None]`.
  - It takes the tracked `TaskPullRequest` rows of tasks in `repo.project_id`, with `connection_id == conn.id`
    and `providers.parse_pr_url(row.url, conn).path == providers.repo_path(repo.url)`.
  - Of those, it uses the one with the latest `last_checked_at`.
  - It returns `(error, limited)` for that row, where `branch_mismatch` maps to `None`, or `(None, None)` when
    there are no rows.

- [ ] **Step 1: Write the failing tests:**
  - `test_repo_shows_the_latest_pr_read_problem`: two rows for the repository; the newer one has
    `error="forbidden"` → `GET /api/projects/PAY/repositories` (use the route the repo list really has) gives
    `pr_error == "forbidden"`.
  - When the newer one is clean and only the older one failed → `pr_error is None`.
  - A row for another repository's URL is ignored.
- [ ] **Step 2: Run to see them fail.** Expected: FAIL, because the field is missing.
- [ ] **Step 3: Implement.** Only when `conn is not None`.
- [ ] **Step 4: Run to see them pass,** plus `tests/projects`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(git): a repository shows when its pull requests can't be read`.

---

### Task 7: Frontend git texts, the badge and repository settings

**Files:**
- Modify:
  - `frontend/src/lib/api-types.ts`: regenerate with `cd frontend && npm run gen:api`;
  - `frontend/src/lib/git.ts`:
    - `TOKEN_HELP.github`, and `TOKEN_HELP.gitea` if it falls short;
    - `CHECKS` and `REVIEW`, with `unknown`;
    - a new `pullRequestProblem`;
    - `pullRequestText`;
  - `frontend/src/components/git/PullRequestBadge.tsx`;
  - `frontend/src/components/project/RepoEditor.tsx`.
- Test: `frontend/src/components/git/__tests__/Git.test.tsx`,
  `frontend/src/components/project/__tests__/RepoEditor.test.tsx`, and `frontend/src/lib/__tests__/git.test.ts`
  (new).

**Interfaces:**
- Consumes: `PullRequestOut.error`, `limited`, `host` and `next_check_at`; `RepoOut.pr_error` and `pr_limited`.
- Produces:
  - `pullRequestProblem(code: string, kind: GitKind | null) -> string`, the spec §3 table. "GitHub" is replaced
    by `HOST_NAME[kind]`. The `forbidden` permission sentence is GitHub's; GitLab's and Gitea's use their token
    hint's words.
  - `limitedText(limited: string | null) -> string | null`, giving:
    - "Checks unknown: the token can't read commit statuses or checks.";
    - "Review unknown: the token can't read reviews.";
    - both sentences when both are missing.
  - `pullRequestText(pr)` returns `"PR · can't read"` when `pr.error` is set.

- [ ] **Step 1: Write the failing tests:**
  - `git.test.ts`:
    - every code in the spec table maps to its row;
    - `pullRequestProblem("forbidden", "github")` equals the spec's row exactly;
    - `pullRequestProblem("unauthorized", "gitlab")` starts with "GitLab rejected the token";
    - `TOKEN_HELP.github` contains "Commit statuses" and "Checks";
    - `pullRequestText` with `checks: "unknown"` gives "PR open · checks unknown".
  - `Git.test.tsx`: the badge with `error: "forbidden"` shows "PR · can't read", has the pink tone class, and its
    `title` is the full reason.
  - `RepoEditor.test.tsx`: a repo with `pr_error: "forbidden"` shows "Can't read pull requests: GitHub refused the
    token (forbidden). …" beside the webhook pill.
- [ ] **Step 2: Run to see them fail.**
  Run: `cd frontend && npx vitest run src/lib/__tests__/git.test.ts src/components/git src/components/project`
  Expected: FAIL.
- [ ] **Step 3: Implement.** The badge's accessible name includes the reason.
- [ ] **Step 4: Run to see them pass,** then `npx tsc --noEmit`, `npm run lint` and `npm test`. Expected: PASS
  with no errors.
- [ ] **Step 5: Commit**: `feat(git): say in words when a pull request can't be read, and ask for the right
  token permissions`.

---

### Task 8: Frontend workflow panel and chat state

**Files:**
- Modify:
  - `frontend/src/lib/workflow.ts`:
    - `NEEDS_TEXT.merge_confirmation = "Agent merged · confirming"`;
    - `ESCALATION_REASON_TEXT.merge_not_confirmed`;
    - `ACCEPTABLE_REASONS` gains `"merge_not_confirmed"`;
  - `frontend/src/components/workflow/WorkflowPanel.tsx`;
  - `frontend/src/lib/chats.ts`: a `"merging"` case;
  - any `Record<ChatState, …>` or `Record<WorkflowNeeds, …>` that `tsc` flags.
- Test: `frontend/src/components/workflow/__tests__/WorkflowPanel.test.tsx`, `frontend/src/lib/__tests__/workflow.test.ts`,
  and the chats lib or ChatView tests.

**Interfaces:**
- Consumes: `pullRequestProblem` and `limitedText` (Task 7); `Workflow.needs`, which can be
  `"merge_confirmation"`; `escalation_reason`, which can be `"merge_not_confirmed"`.

- [ ] **Step 1: Write the failing tests.** In `WorkflowPanel.test.tsx`:
  - **The new wait:** for `needs: "merge_confirmation"`, the panel shows the spec's confirming line, with "GitHub"
    from `pull_request.host`, and a secondary (ghost) **Mark merged** button that posts `human-review`.
  - **The escalation:** for `merge_not_confirmed` with `pull_request.error: "forbidden"`, it shows "The agent
    merged the pull request, but MegooColab couldn't confirm it." plus the forbidden reason, and an accept button
    labelled **Mark merged** (no "Accept"). With `error: null` and `state: "open"`, it shows "GitHub still shows it
    open."
  - **A read problem** under the PR in any state: "MegooColab can't read this pull request: <reason>. It tries
    again at <time>."; or, for a partial read, the `limitedText` line.

  In the chats tests: `"merging"` with PR 3 gives "merging · PR #3", and `"merging"` isn't in `WAITING`.
- [ ] **Step 2: Run to see them fail.**
  Run: `cd frontend && npx vitest run src/components/workflow src/lib src/components/chats`
  Expected: FAIL.
- [ ] **Step 3: Implement.** Format the time the way the panel's other times are formatted.
- [ ] **Step 4: Run to see them pass,** then `npx tsc --noEmit`, `npm run lint` and `npm test`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(workflow): show an agent's merge being confirmed, and a clear way out when it can't
  be`.

---

### Task 9: End to end

**Files:**
- Modify:
  - `frontend/e2e/helpers/fakeGit.ts`: `FakePr` gains `forbid?: ("pull" | "status" | "check-runs" |
    "reviews")[]`, and a listed call answers 403 `{ message: "Resource not accessible by personal access token" }`;
  - `frontend/e2e/git.spec.ts`, section 7.

- [ ] **Step 1: Extend section 7.** These steps go after `approved PR #3 and merged it`, in place of the current
  merge lines:

```ts
await expect.poll(async () => (await get<Workflow>(request, `/api/tasks/${THIRD}/workflow`)).needs, { timeout: 30_000 })
  .toBe("merge_confirmation");
await expect(third.getByText("Agent merged · confirming")).toBeVisible();
const dash = await get<{ needs: { ref: string }[] }>(request, "/api/dashboard"); // check the real response shape
expect(dash.needs.map((n) => n.ref)).not.toContain(THIRD);
// the token can't read the PR: MegooColab asks a person
fake.prs.set(3, { state: "open", merged: false, checks: "success", reviews: [], forbid: ["pull"] });
// send a pull_request "synchronize" delivery for #3, signed with made.secret
await expect.poll(async () => (await get<Workflow>(request, `/api/tasks/${THIRD}/workflow`)).escalation_reason, { timeout: 30_000 })
  .toBe("merge_not_confirmed");
await expect(third.getByText("The agent merged the pull request, but MegooColab couldn't confirm it.")).toBeVisible();
await expect(third.getByText(/GitHub refused the token \(forbidden\)/)).toBeVisible();
await expect(third.getByRole("button", { name: "Mark merged" })).toBeVisible();
// the token is fixed, but still can't read checks: the merge is seen and the round finishes by itself
fake.prs.set(3, { state: "closed", merged: true, checks: "success", reviews: [], forbid: ["status", "check-runs"] });
// the existing merged3 delivery, then the existing poll for "finished"
```

- [ ] **Step 2: Run it** on a fresh megoo-e2e stack:

```bash
SPECS="git.spec.ts" bash C:/Users/hammad/AppData/Local/Temp/claude/c--Projects-MegooColab/d21d3e46-3e86-4e0e-b093-aea45e487cb8/scratchpad/e2e-mobile.sh
```

Read the tail of that scratchpad's `e2e-mobile.txt`.

Expected: `git.spec.ts` PASSES. If the script is gone, bring the stack up the same way the other e2e runs do,
with the `megoo-e2e` project only.

- [ ] **Step 3: Commit**: `test(e2e): an agent's merge is confirmed quietly, escalates when it can't be read, and
  finishes once it is`.
