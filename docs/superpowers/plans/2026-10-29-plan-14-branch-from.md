# Branch from Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agents start every task branch from a known, freshly fetched branch (the repository's default, or the task's "Branch from"), and a production fix is delivered into its start branch and back-merged into the default branch, with both pull requests tracked until merged.

**Architecture:** The server sends the runner the task's Branch from, any recorded start branch and the project's repositories (`run_start.branch`). The runner matches its folder's `origin` to a repository, fetches, creates the worktree from `origin/<start>`, and reports the resolved branches once (run update kind `branch`), which the server records on the task (`start_branch`, `back_merge_into`). The finish run is told both branches; `report_finish` accepts a back-merge result; `task_pull_requests` holds up to two rows per task (`kind` main / back_merge), and a production fix in pull-request mode waits until both are merged.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (backend), Go (runner), Next 16 / React 19 / TanStack Query / vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-10-29-branch-from-design.md`

## Global Constraints

- Task branch names stay `megoo/<KEY>-<slug>`; the back-merge branch is `megoo/<KEY>-<slug>-to-<default branch, slugged>`.
- Branch from: optional, a git branch name (`git check-ref-format --branch` rules), at most 200 characters; empty/null means "the default branch".
- New error codes, verbatim: `branch_from_locked` (409), `invalid_branch_name` (422), `start_branch_missing`, `repository_not_matched` (runner failure codes), `back_merge_required`, `back_merge_not_expected`, `back_merge_pr_url_required` (422).
- Runner capability `branch/1`; problem text, verbatim: `runner too old to choose the start branch — update megoocolab-runner`.
- No force pushes or history rewriting; the finish text's existing hard rules stay. Task text stays untrusted: only the prompt's explicit branches decide delivery; "unless the task says otherwise" is removed.
- Existing projects and tasks keep working: empty Branch from = default branch; unmatched repository + empty Branch from = today's behaviour (HEAD).
- Migrations: generated against `megoo_migrate` (`DEV_DATABASE_URL=…/megoo_migrate bash scripts/makemigration.sh "<name>"`), named constraints, downgrade round trip checked. Never two pytest runs at once.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A repository whose stored default is the unchecked `"main"` but whose real branch is `master`: an implicit start falls back to `origin/HEAD`, then HEAD, and the run succeeds (Task 3 test `TestResolveImplicitDefaultFallsBackToOriginHead`).
2. No `origin`, or the fetch fails (offline): the local branch of that name is used and the run log says so (Task 3 `TestResolveOfflineUsesLocalBranch`).
3. A second `branch` report for the same task (a rerun after the worktree was removed, a duplicate message): the first recorded values never change (Task 2 `test_branch_report_records_once`).
4. The `develop` PR is closed while the `main` PR merged: the task escalates `pr_closed` and is not finished (Task 5 `test_back_merge_closed_escalates_even_if_main_merged`).
5. Branch names at the edges: `feature/x` and `release/1.2` valid; `main..x`, `-x`, `a b`, `x.lock`, `x/`, `@`, a 201-character name invalid (Task 1 `test_branch_name_rules`).

---

### Task 1: Task fields, Branch from validation and locking

**Files:**
- Modify: `backend/app/tasks/models.py` (Task), `backend/app/workflow/models.py` (TaskWorkflow), `backend/app/git/models.py` (TaskPullRequest)
- Create: `backend/app/tasks/branches.py`, migration in `backend/migrations/versions/`
- Modify: `backend/app/tasks/schemas.py`, `backend/app/tasks/service.py`
- Test: `backend/tests/tasks/test_branch_from.py`

**Interfaces:**
- Produces:
  - `Task.branch_from: str | None` (String(200)), `Task.start_branch: str | None` (String(200)), `Task.back_merge_into: str | None` (String(200)).
  - `TaskWorkflow.back_merge_branch: str | None` (String(300)), `TaskWorkflow.back_merge_pr_url: str | None` (String(1000)).
  - `TaskPullRequest.kind: str` (String(20), part of the primary key `(task_id, kind)`, server default `'main'`); constants `PR_MAIN = "main"`, `PR_BACK_MERGE = "back_merge"` in `app/git/models.py`. (Only the column and PK here; Task 5 uses them.)
  - `app/tasks/branches.py`: `valid_branch_name(name: str) -> bool`; `async def branch_from_locked(db, task: Task) -> bool` — True when `task.start_branch` is set, or the task's workflow is `connect_only` and not `idle`.
  - `TaskCreate.branch_from`, `TaskUpdate.branch_from: str | None` (stripped; `""` → None). `TaskOut` gains `branch_from`, `start_branch`, `back_merge_into`, `branch_from_locked: bool`.

- [ ] **Step 1: Write the failing tests** in `tests/tasks/test_branch_from.py`:
  - `test_branch_name_rules`: `valid_branch_name` is True for `main`, `develop`, `feature/x`, `release/1.2`; False for `""`, `main..x`, `-x`, `a b`, `x.lock`, `x/`, `/x`, `a//b`, `@`, `a@{b`, `x~1`, `x^`, `x:y`, `x?`, `x*`, `x[`, `x\\y`, `.x`, `a/.b`, `x.`, a control character, `"a" * 201`.
  - `test_branch_from_set_and_cleared`: PATCH `{branch_from: "main"}` → 200, `TaskOut.branch_from == "main"`, a `field_changed` event `{field: "branch_from", from: None, to: "main"}`; PATCH `{branch_from: ""}` → `branch_from is None`; create with `branch_from: " main "` stores `"main"`.
  - `test_invalid_branch_from_422`: PATCH `{branch_from: "main..x"}` → 422 `invalid_branch_name`.
  - `test_branch_from_locked_once_started`: set `task.start_branch = "develop"` in the DB → `TaskOut.branch_from_locked is True`; PATCH `{branch_from: "main"}` → 409 `branch_from_locked`; PATCH with the same value as stored → 200 (no change is not refused).
  - `test_branch_from_locked_for_started_connect_only`: a `connect_only` workflow in `running` → 409; in `idle` → 200.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/tasks/test_branch_from.py -q` — Expected: FAIL (import error / unknown field).
- [ ] **Step 3: Implement.** Add the columns and model constants; add `branch_from` to `TRACKED_FIELDS`; validation in the schemas (strip, empty → None, then `valid_branch_name` raising 422 `invalid_branch_name` from the service, not a pydantic error, so the code matches); lock check in `update_task` only when the value changes. Generate one migration for all of Task 1's columns plus the `task_pull_requests` PK change (drop `task_pull_requests_pkey`, add `kind` with server default `'main'`, create PK `(task_id, kind)`); check `downgrade -1` / `upgrade head` on `megoo_migrate` (the downgrade deletes `back_merge` rows before restoring the single-column PK).
- [ ] **Step 4: Run** the same command — Expected: PASS. Then `uv run pytest tests/tasks -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(tasks): Branch from field, recorded start branch, back-merge columns`.

### Task 2: Server side of the protocol (run_start.branch, branch report, capability)

**Files:**
- Modify: `backend/app/runner/protocol.py`, `backend/app/runner/registry.py`, `backend/app/agent_runs/service.py`, `backend/app/agents/service.py`
- Test: `backend/tests/runner/test_branch_protocol.py`

**Interfaces:**
- Consumes: Task 1's `Task.branch_from`, `start_branch`, `back_merge_into`; `ProjectRepository.url`, `default_branch`.
- Produces:
  - `RunBranchRepo(url: str, default_branch: str)`, `RunBranch(branch_from: str = "", start_branch: str = "", repositories: list[RunBranchRepo] = [])`; `RunStart.branch: RunBranch | None`, sent for every task run (workflow or not; **not** in `V2_START_FIELDS`), never for answering runs.
  - `BRANCH_CAPABILITY = "branch/1"`, `BRANCH_PROBLEM` (Global Constraints text) in `registry.py`; `agent_problems` appends it when the capability is missing.
  - Run update kind `"branch"`, data `{start_branch, default_branch, repository_url}`; `sanitize_update` keeps them (branch names via `valid_branch_name`, else dropped; URL ≤ 1000 chars).
  - `async def record_start_branch(db, task: Task, start_branch: str, default_branch: str) -> bool` in `agent_runs/service.py`: when `task.start_branch is None` and `start_branch` is non-empty, sets `start_branch` and `back_merge_into = default_branch if default_branch and default_branch != start_branch else None`, records task event `branch_started` `{start_branch, back_merge_into}`; True if it recorded. A `branch` update calls it instead of storing an `agent_branch` event.
  - `RUNNER_FAILURE_CODES` gains `start_branch_missing`, `repository_not_matched`.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_start_carries_branch_for_plain_and_workflow_runs`: a project with repositories `https://github.com/acme/pay` (`develop`) and a task with `branch_from="main"` → the plain run's `run_start` has `branch == {"branch_from": "main", "start_branch": "", "repositories": [{"url": "https://github.com/acme/pay", "default_branch": "develop"}]}`, as does a workflow run; once `start_branch` is recorded it carries `"start_branch": "main"`.
  - `test_branch_report_records_once`: a `branch` update `{start_branch: "main", default_branch: "develop"}` → task `start_branch == "main"`, `back_merge_into == "develop"`, one `branch_started` event, no `agent_branch` event; a second update `{start_branch: "develop", default_branch: "develop"}` changes nothing.
  - `test_branch_report_same_as_default_has_no_back_merge`: `{start_branch: "develop", default_branch: "develop"}` → `back_merge_into is None`.
  - `test_branch_report_bad_names_ignored`: `{start_branch: "a..b"}` records nothing.
  - `test_runner_without_branch_capability_leaves_task_runs_queued`: hello with `["workflow/1"]` only → a queued task run stays queued and the agent's problems include `BRANCH_PROBLEM`; hello with `["workflow/1", "branch/1"]` → it starts. An answering run still starts with only `workflow/1`.
  - `test_new_failure_codes_kept_as_reason`: `run_finished` failed with error `start_branch_missing` → the run's reason is `start_branch_missing`.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/runner/test_branch_protocol.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.** `_claim_next`'s `runnable`: both capabilities → all; `workflow/1` only → `question_id IS NOT NULL`; neither → `false()`. Update existing tests that send a hello with only `workflow/1` and expect task runs to start (add `branch/1`; the shared hello helper in `tests/runner` is the place).
- [ ] **Step 4: Run** `uv run pytest tests/runner tests/agent_runs tests/agents -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(runner): run_start carries the start branch; branch report recorded once; branch/1 capability`.

### Task 3: Runner — resolving and fetching the start branch

**Files:**
- Create: `runner/internal/startbranch/startbranch.go`, `runner/internal/startbranch/startbranch_test.go`
- Modify: `runner/internal/protocol/protocol.go` (types only)

**Interfaces:**
- Produces:
  - `protocol.RunBranchRepo{URL, DefaultBranch}` (`json:"url"`, `json:"default_branch"`), `protocol.RunBranch{BranchFrom, StartBranch string; Repositories []RunBranchRepo}` (`json:"branch_from"`, `json:"start_branch"`, `json:"repositories"`), `RunStart.Branch *RunBranch` (`json:"branch,omitempty"`).
  - `startbranch.NormalizeURL(u string) string` — lower-cased `host/path`, credentials, scheme, port, trailing `/` and `.git` removed; scp form `git@host:owner/repo` handled.
  - `startbranch.Resolve(ctx context.Context, logw io.Writer, repo string, spec *protocol.RunBranch) (Result, error)`; `type Result struct { StartPoint, StartBranch, DefaultBranch, RepositoryURL string; Report bool }`. `StartPoint == ""` means "HEAD, as today".
  - `startbranch.ErrStartBranchMissing`, `startbranch.ErrRepositoryNotMatched`.

Resolution (the tests pin it; the order matters):
1. `spec == nil` → `Result{}` (HEAD, no report).
2. `spec.StartBranch != ""` (recorded) → start = it, explicit; no report.
3. Else match `git remote get-url origin` by `NormalizeURL` equality; no match and exactly one repository → that one.
   - `BranchFrom != ""`: no repository → `ErrRepositoryNotMatched`; else start = BranchFrom (explicit), default = repo's default.
   - empty: repository → start = default = its default (implicit); none → `Result{}`.
4. Start point: `git fetch origin refs/heads/<start>:refs/remotes/origin/<start>` (bounded by the worktree add timeout) succeeds → `origin/<start>`; else local `refs/heads/<start>` → `<start>` (log "using the local <start>: <why>"); else implicit → `refs/remotes/origin/HEAD`'s branch `B` → start = default = `B`, point `origin/B` (logged), else current HEAD's branch name with point `""` (logged; no report if detached); else explicit → `ErrStartBranchMissing`.
5. `Report = true` for steps 3–4 results with a non-empty StartBranch; `RepositoryURL` = the matched repository's URL.

- [ ] **Step 1: Write the failing tests** (temp repos: a bare `origin` with branches `main` and `develop`, a clone as the developer's folder):
  - `TestNormalizeURL`: `https://github.com/Acme/Pay.git`, `git@github.com:acme/pay.git`, `ssh://git@github.com:22/acme/pay`, `https://user:tok@github.com/acme/pay/` all → `github.com/acme/pay`; `https://gitea.local/x/y` → `gitea.local/x/y`.
  - `TestResolveDefaultFromMatchedRepository`: repos `[{other, main}, {<origin url>, develop}]`, no Branch from → StartPoint `origin/develop`, Start = Default = `develop`, Report.
  - `TestResolveBranchFromFetchesLatest`: a commit pushed to origin `main` after the clone → StartPoint `origin/main` and `git rev-parse origin/main` equals the new commit; Default `develop`.
  - `TestResolveBranchFromWithoutMatchFails`: two repositories, neither matching → `ErrRepositoryNotMatched`.
  - `TestResolveSingleRepositoryUsedWithoutMatch`: one repository with a different URL → its default is used.
  - `TestResolveNoRepositoriesKeepsHead`: empty list, no Branch from → `Result{}`, no error.
  - `TestResolveExplicitMissingFails`: Branch from `hotfix-base` (nowhere) → `ErrStartBranchMissing`.
  - `TestResolveImplicitDefaultFallsBackToOriginHead`: origin's HEAD is `master`, stored default `main` (missing) → StartPoint `origin/master`, Start = Default = `master`, log mentions the fallback.
  - `TestResolveOfflineUsesLocalBranch`: origin URL pointing at a removed directory, local `develop` exists → StartPoint `develop`, log line present.
  - `TestResolveRecordedStartNotReported`: `StartBranch: "main"` → StartPoint `origin/main`, Report false.
- [ ] **Step 2: Run** `cd runner && go test ./internal/startbranch/` — Expected: FAIL (package missing).
- [ ] **Step 3: Implement** with the `gitstate.Run`/`RunContext` helpers the worktree package uses (no repo hooks, same environment).
- [ ] **Step 4: Run** `go test ./internal/startbranch/ ./internal/protocol/` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(runner): resolve and fetch the start branch`.

### Task 4: Runner — worktree start point, branch report, capability

**Files:**
- Modify: `runner/internal/worktree/worktree.go`, `runner/internal/jobs/manager.go`, `runner/internal/protocol/protocol.go`
- Test: `runner/internal/worktree/worktree_test.go`, `runner/internal/jobs/manager_test.go`, `runner/internal/conn/conn_test.go`

**Interfaces:**
- Consumes: Task 3's `startbranch.Resolve`, `Result`, errors.
- Produces:
  - `worktree.Ensure(ctx, logw, repo, cacheRoot, agentID, taskKey, title string, startPoint func() (string, error)) (path, branch string, created bool, err error)`. `startPoint` is called only when the branch must be created; `""` → `git worktree add -b <branch> <path>` (HEAD), else `... <path> <startPoint>`; its error is returned as is.
  - `protocol.CapabilityBranch = "branch/1"`; hello sends `[workflow/1, branch/1]`.
  - Manager: failure codes `start_branch_missing` / `repository_not_matched` for the two errors (else `worktree_failed`); after a created worktree whose Result has `Report`, `r.emit("branch", {start_branch, default_branch, repository_url})`.

- [ ] **Step 1: Write the failing tests:**
  - `TestEnsureStartsFromGivenPoint`: Ensure with `startPoint` returning `develop` → the new branch's parent commit is `develop`'s tip, not HEAD's; `created` true.
  - `TestEnsureReuseDoesNotCallStartPoint`: second Ensure with a `startPoint` that fails the test if called → reused, `created` false. Same for an existing branch without a worktree (`TestEnsureExistingBranchWithoutWorktree` updated).
  - Manager: `TestRunStartsFromBranchAndReports`: run_start with `branch` for a matching repository → a `run_update` of kind `branch` with `start_branch`/`default_branch` is sent before any agent message; a second run on the same task sends none.
  - `TestRunFailsWithStartBranchMissing`: explicit missing Branch from → run finished `failed`, error `start_branch_missing`, no worktree left.
  - `conn_test`: hello capabilities are `["workflow/1", "branch/1"]`.
- [ ] **Step 2: Run** `cd runner && go test ./internal/worktree/ ./internal/jobs/ ./internal/conn/` — Expected: FAIL.
- [ ] **Step 3: Implement**; update every existing `Ensure` caller and test (`nil` startPoint behaves as `""`).
- [ ] **Step 4: Run** `go test ./...` and `go vet ./...` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(runner): create task branches from the start branch and report it`.

### Task 5: Two pull requests per task

**Files:**
- Modify: `backend/app/git/service.py`, `backend/app/git/jobs.py`, `backend/app/git/router.py`, `backend/app/tasks/service.py`, `backend/app/tasks/schemas.py`, `backend/app/workflow/router.py` (WorkflowOut), `backend/app/workflow/schemas.py` (wherever `WorkflowOut` lives)
- Test: `backend/tests/git/test_back_merge_tracking.py`; existing `tests/git/test_tracking.py` keeps passing

**Interfaces:**
- Consumes: Task 1's `TaskPullRequest.kind`, `PR_MAIN`, `PR_BACK_MERGE`, `TaskWorkflow.back_merge_branch`, `back_merge_pr_url`.
- Produces:
  - `track_pr(db, task, url, kind: str = PR_MAIN) -> TaskPullRequest`; `queue_refresh(db, task_id)` unchanged (one job per task); the `git.pr_refresh` job refreshes every open tracked row of the task; the poll job selects `(task_id, kind)`.
  - `back_off(db, task_id, kind, code)`, `apply_status(db, task_id, kind, status, *, url=None)`, `_lock_row(db, task_id, kind)`.
  - `pull_requests_of_task(db, task_id) -> list[TaskPullRequest]` (replaces `pull_request_of`).
  - `settle_done(db, wf, task, rows: list[TaskPullRequest]) -> bool`: acts only while `waiting_human` + `human_code_review`. Expected rows: main, plus back_merge when `wf.back_merge_pr_url`. Any tracked row `closed` → event `pr.closed` `{url, kind}` and escalation `pr_closed`. Any `branch_mismatch` → no action. Every expected row present, tracked and `merged` → `pr.merged` events/audit per newly merged row, then finish. Otherwise wait (an untracked row needs a person's "PR approved").
  - Branch check in `apply_status`: a `back_merge` row compares the PR head with `wf.back_merge_branch`, a main row with `wf.branch`.
  - `tasks.service.pull_requests_of(db, ids, kind: str = PR_MAIN)`; `TaskOut.back_merge_pull_request: PullRequestOut | None`; `WorkflowOut` gains `back_merge_branch`, `back_merge_pr_url`, `back_merge_pull_request`, `start_branch`, `back_merge_into`, `branch_from`, `finish_outcome`.

- [ ] **Step 1: Write the failing tests** (reuse `tests/git/test_tracking.py` helpers; set `wf.back_merge_pr_url`/`back_merge_branch` and track both rows directly through the service):
  - `test_both_prs_merged_finishes`: main merged → still waiting; back_merge merged → finished, two `pr.merged` events.
  - `test_back_merge_closed_escalates_even_if_main_merged`: main merged, back_merge closed → escalation `pr_closed`, a `pr.closed` event with `kind == "back_merge"`, not finished.
  - `test_back_merge_branch_mismatch_waits`: back_merge PR head `megoo/other` ≠ `wf.back_merge_branch` → row error `branch_mismatch`, no finish.
  - `test_refresh_job_reads_both_rows`: one `git.pr_refresh` job → both rows' state updated.
  - `test_task_and_workflow_out_show_both_prs`: `GET /api/tasks/{key}` has `pull_request` and `back_merge_pull_request`; `GET …/workflow` has `back_merge_pull_request`, `start_branch`, `back_merge_into`, `finish_outcome`.
  - `test_webhook_refreshes_back_merge_row`: a delivery naming the back-merge PR's number refreshes that task.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/git/test_back_merge_tracking.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement**; move every `pull_request_of`/`settle_done` caller to the list form.
- [ ] **Step 4: Run** `uv run pytest tests/git tests/workflow tests/tasks -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(git): track the back-merge pull request beside the main one`.

### Task 6: Finish — telling the agent, the back-merge, report_finish, waiting for both

**Files:**
- Modify: `backend/app/workflow/engine.py` (finish `extra` section), `backend/app/workflow/finish.py`, `backend/app/mcp_server/workflow_tools.py`, `backend/app/workflow/methodology_texts/defaults/finish.md`, `backend/app/workflow/methodology_history.py`
- Test: `backend/tests/workflow/test_finish_branches.py`

**Interfaces:**
- Consumes: Task 1 task/workflow fields; Task 5's `track_pr(..., kind)`, `settle_done(..., rows)`, `pull_requests_of_task`.
- Produces:
  - Finish prompt section, exactly:
    ```
    ## Finishing
    Finishing option: <option>
    Start branch: <start_branch>
    Back-merge into: <back_merge_into>
    ```
    The last line only when `back_merge_into` is set. When `start_branch` is None: `Start branch: unknown — deliver into the branch the task branch was created from (git merge-base helps)`.
  - `report_finish(db, run, outcome, branch, pr_url, tests_passed, back_merge_branch: str | None = None, back_merge_pr_url: str | None = None)`. With `task.back_merge_into` set and option ≠ `keep_branch`: `back_merge_branch` required (`back_merge_required`); outcome `pr_opened` also needs a valid `back_merge_pr_url` (`back_merge_pr_url_required`, same URL checks as `pr_url`). Without a back-merge (or `keep_branch`), either argument → `back_merge_not_expected`. Stores `wf.back_merge_branch`, `wf.back_merge_pr_url`; tracks the second PR with `kind=PR_BACK_MERGE`; `finish.reported` event carries both.
  - MCP `report_finish` tool gains `back_merge_branch: str | None = None, back_merge_pr_url: str | None = None`. MCP `get_workflow` returns `"branches": {"start": …, "back_merge_into": …}`: the recorded values; for a `connect_only` workflow with nothing recorded, start = `branch_from` or the single repository's default (else None) and back_merge_into = that repository's default when it differs from start.
  - `_handle_finish` waits on `human_code_review` when the option is `pull_request` and (human review is required, or the outcome is `pr_opened` and `wf.back_merge_pr_url` is set).
  - `finish.md`: base determination replaced by the prompt's Start branch; "Target the project's default branch unless the task says otherwise" → "Target the start branch named in your prompt"; a new "Back-merge" section (pull request: create `megoo/<KEY>-<slug>-to-<back-merge branch>` from `origin/<back-merge branch>`, merge the task branch, resolve conflicts, full suite + `record_tests`, push, open the second PR into the back-merge branch; merge locally: merge into the start branch, re-run tests, then into the back-merge branch, re-run tests; plain git: push both branches; keep branch: nothing). "When something fails" gets the one exception: conflict resolution in the back-merge only, keeping the intent of both sides, each conflicted file recorded with `record_decision`, three-attempt rule then `ask_human`. Append the new SHA-256 to `DEFAULT_HISTORY["finish"]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_finish_prompt_names_start_and_back_merge`: task with `start_branch="main"`, `back_merge_into="develop"` → the finish run's prompt contains `Start branch: main` and `Back-merge into: develop`; with `back_merge_into=None` no `Back-merge into` line; with `start_branch=None` the `unknown` line.
  - `test_report_finish_back_merge_rules`: production fix + `pull_request` → missing back-merge → 422 `back_merge_required`; `pr_opened` without `back_merge_pr_url` → `back_merge_pr_url_required`; no back-merge task + `back_merge_branch` → `back_merge_not_expected`; `keep_branch` + back-merge task + no back-merge args → accepted.
  - `test_production_fix_waits_for_both_prs_without_human_review`: project without human review, production fix, both PRs reported → `waiting_human`/`human_code_review`; both merged (Task 5 path) → finished.
  - `test_normal_fix_without_human_review_finishes_on_report`: no back-merge → finished on report (unchanged).
  - `test_merge_local_with_back_merge_finishes_on_report`.
  - `test_get_workflow_reports_branches`: runner task with recorded values; connect-only task with `branch_from="main"` and one repository defaulting to `develop` → `{"start": "main", "back_merge_into": "develop"}`.
  - `test_finish_text_back_merge_section`: the default `finish.md` contains `Back-merge into`, `-to-`, `record_decision` within the back-merge section, and no longer contains `unless the task says otherwise`.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/workflow/test_finish_branches.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/workflow tests/git tests/mcp -q` (includes `test_default_history_ends_with_the_current_texts`), then the whole backend suite `uv run pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(workflow): finish delivers to the start branch and back-merges production fixes`.

### Task 7: Frontend

**Files:**
- Modify: `frontend/src/lib/api-types.ts` (regenerated: `npm run gen:api`), `frontend/src/components/task/TaskFields.tsx`, `frontend/src/components/workflow/WorkflowPanel.tsx`, `frontend/src/lib/workflow.ts`, `frontend/src/components/board/TaskCard.tsx`, `frontend/src/lib/agents.ts`, `frontend/src/lib/errors.ts`, `frontend/src/components/task/ActivityThread.tsx`
- Test: `frontend/src/components/task/__tests__/branch-from.test.tsx`, `frontend/src/components/workflow/__tests__/branches.test.tsx`, `frontend/src/lib/__tests__/workflow-branches.test.ts`

**Interfaces:**
- Consumes: Task 1 `TaskOut` fields; Task 5/6 `WorkflowOut` fields; `GET /api/projects/{ref}/repositories`.
- Produces: `branchLine(start: string | null, backMergeInto: string | null, branchFrom: string | null): string` in `lib/workflow.ts`.

Copy, verbatim:
- `branchLine`: `Starts from main. Delivers to main, then develop.` / `Starts from develop. Delivers to develop.` / `Will start from main.` / `Will start from the default branch.`
- Field: label `Branch from`; placeholder `<default> (default)` when the project has exactly one repository, else `Default branch`; when locked, read-only with hint `Locked: work started from <start_branch>.` (or `Locked: the workflow has started.` when nothing is recorded).
- Errors: `invalid_branch_name` → `That isn't a valid branch name.`; `branch_from_locked` → `Branch from can't change once work has started.`
- Run failure reasons: `start_branch_missing` → `the branch to start from doesn't exist`; `repository_not_matched` → `the agent's folder doesn't match any of the project's repositories`.
- Back-merge PR: label `Into <back_merge_into>:` before its badge. Kept-branch note (`finish_outcome === "branch_kept"` and a back-merge): `This fix still has to reach <start_branch> and <back_merge_into>.`
- Board badge when `branch_from` is set, unless work has started and no back-merge exists (`start_branch && !back_merge_into`, i.e. it turned out to be the default): `from <branch_from>`, title `Starts from <branch_from> instead of the default branch`.
- Activity `branch_started`: `started work from <start_branch>`.

- [ ] **Step 1: Write the failing tests:**
  - `workflow-branches.test.ts`: the four `branchLine` strings above.
  - `branch-from.test.tsx`: the field shows placeholder `develop (default)` for one repository; typing `main` and blurring PATCHes `{branch_from: "main"}`; clearing PATCHes `{branch_from: null}`; locked task renders read-only with `Locked: work started from main.`; a 422 `invalid_branch_name` shows the message.
  - `branches.test.tsx`: WorkflowPanel shows `Starts from main. Delivers to main, then develop.`, two PR badges with `Into develop:`, and the kept-branch note; TaskCard shows `from main`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/lib/__tests__/workflow-branches.test.ts src/components/task/__tests__/branch-from.test.tsx src/components/workflow/__tests__/branches.test.tsx` — Expected: FAIL.
- [ ] **Step 3: Implement** (regenerate `api-types.ts` first with the backend from Task 6).
- [ ] **Step 4: Run** `npx vitest run`, `npx tsc --noEmit`, `npm run lint` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(frontend): Branch from field, where work starts and is delivered, both pull requests`.
