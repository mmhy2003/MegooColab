# MegooColab Plan 7 — Git Integration, Notifications, Admin and Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close v1 (spec §11 milestone 7).
- **Git integration.** MegooColab follows each task's pull request or merge request on GitHub, GitLab and Gitea/Forgejo, using read-only tokens and webhooks. When a project requires human code review, the Done stage moves on by itself once a person merges the pull request in the git host. Plain git keeps the "mark merged" button. Tasks show their branch and pull request.
- **Notifications.** An in-app notification centre and email for "needs you", assignments, mentions, an agent going offline mid-task, and questions waiting for an answer, with per-user preferences.
- **Admin.** Git connections, defaults for new projects and the dreaming schedule.
- **Audit.** Agent sessions are audited.
- **Installation.** A guide good enough to install from the docs alone.
- **Plan 6 follow-ups.** The leftovers from Plan 6's final review.

**Architecture:**
- **Backend:** two new modules.
  - `app/git`:
    - admin-managed provider connections, with the token and webhook secret encrypted by `core.crypto`;
    - one provider client per kind, on `httpx`;
    - a `task_pull_requests` row per finished task;
    - a periodic poll job, plus a webhook endpoint that only triggers a refresh.
  - `app/notifications`: rows per recipient, per-kind preferences, an email job, and a per-user live event.
- **Workflow:** `engine.wait_for` becomes async and notifies. Finish accepts a pushed branch without a pull-request URL for plain-git projects. A merged pull request finishes a workflow that waits on `human_code_review`; a closed one escalates `pr_closed`.
- **Runner:** unchanged. Opening pull requests still happens on the developer's laptop with their own credentials (GIT-2).
- **Frontend:**
  - a notification bell, page and preferences;
  - an `@` mention picker and mention rendering;
  - an Admin → Git page and a connection picker on project repositories;
  - pull-request badges on tasks and cards;
  - admin settings for dreaming and new-project defaults.

**Tech Stack:** Plans 1–6 stack. `httpx` moves from the dev dependencies to runtime dependencies; there are no other new dependencies.

**Spec:** [docs/brd.md](../../brd.md). This plan covers:
- §6.9 GIT-1 to GIT-5
- §6.10 NOT-1, NOT-2
- §6.11 ADM-1 (git provider connections, defaults for new projects, dreaming schedule), ADM-2 (agent sessions), ADM-3 (answering runs)
- §4 and §12 "a new organization can install and configure MegooColab from the docs alone"
- WF-6a "waits … until a person approves the PR/MR in the git host"

The finishing options stay as specified (WF-6b): opening a pull request is the default, and a person merges it in the git host.

**Builds on:** Plans 1–6 on `main`. Reuse:
- **Workflow:** `workflow.engine` (`wait_for`, `escalate`, `ACCEPT_HANDLERS`, `rerun`, `record_workflow_event`, `finishing_option`, `requires_human_review`, `owner_id`) and `workflow.finish` (`report_finish`, `finish_workflow`, `approve_human_review`, `OUTCOME_OF`)
- **Projects:** `projects.models.ProjectRepository`, `RepoProvider`, and `projects.router` repositories
- **Infrastructure:** `jobs.queue` (`register`, `register_periodic`, `enqueue` with `dedupe_key`), `core.crypto.encrypt/decrypt`, `core.email` (`get_mailer`, `Mailer`, `OutboxMailer`), `core.events` (`Event(user_id=…)`, `publish`), `audit.record`
- **Domain:** `agent_runs.service` (`_send_start`, `_transition`, `fail_disconnected_runs`, `cancel_run`), `agents.service.admin_agents_out`, `a2a.routing`, `a2a.service`, `memory.dream.dream_tick`, `org.models.OrgSettings`
- **Frontend:** `Header`, `Markdown`, `CommentBox`, `WorkflowPanel`, `TaskCardView`, admin pages, `realtime.invalidationsFor`

## Global Constraints

**Git connections (ADM-1, GIT-1)**
- Fields: `name` 1–100 (unique), `kind` `github|gitlab|gitea` (Gitea covers Forgejo), `base_url` (`http(s)://host[:port][/prefix]`, ≤ 300, no trailing slash, no credentials or query), `token` 1–500 (write-only, encrypted), `webhook_secret` 0–200 (write-only, encrypted; empty means no webhooks).
- API bases:
  - github: `https://api.github.com` when the host is `github.com`, else `{base_url}/api/v3`
  - gitlab: `{base_url}/api/v4`
  - gitea: `{base_url}/api/v1`
- Auth headers:
  - github: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`
  - gitlab: `PRIVATE-TOKEN: <token>`
  - gitea: `Authorization: token <token>`
- Every provider call has a 10 s timeout, never follows redirects to another host, and never puts the token in a URL, a log line, an error, an audit entry or an API response (only `token_set: bool`).
- Admins manage connections. A project manager links each of the project's repositories to a connection (`project_repositories.connection_id`, SET NULL). That link is the per-project token selection of GIT-3.

**Pull requests (GIT-3, GIT-5)**
- Pull-request URL shapes: github `{web}/{owner}/{repo}/pull/{n}`, gitlab `{web}/{namespace…}/{project}/-/merge_requests/{n}`, gitea `{web}/{owner}/{repo}/pulls/{n}`, where `{web}` is the connection's `base_url`.
- A pull request is **tracked** only when its URL matches the `base_url` of a connection linked to one of the task's project repositories, **and** its owner/repo path equals that repository's path (parsed from `https://`, `ssh://` or `git@host:` URLs, without `.git`). Anything else is **untracked**: the human button stays the only way to finish.
- States: `open | merged | closed`; checks `success | failure | pending | none`; review `approved | changes_requested | none`.
  - GitHub: `merged` → merged, else `state`. Checks combine `GET /repos/{o}/{r}/commits/{sha}/status`.`state` and `…/check-runs` conclusions: any failure, cancellation or timeout is `failure`; any run not completed is `pending`; all successful is `success`; none at all is `none`. Review is the latest review per reviewer from `…/pulls/{n}/reviews`.
  - GitLab: `state` (`opened`→open, `merged`, `closed`/`locked`→closed); checks from `head_pipeline.status` (`success`; `failed`/`canceled`→failure; none → `none`; else pending); review `approved` from `…/approvals`.`approved`.
  - Gitea: `merged` → merged, else `state`; checks from the combined status `state` (`error`→failure); reviews as GitHub.
- Polling: `git.pr_poll` every **120 s**, at most **50** rows, oldest `next_check_at` first, only `state=open` rows. On an error: keep the old state, store an error code (`unauthorized|not_found|unreachable|rate_limited|bad_response`), and back off with `next_check_at = now + min(2^failures, 60)` minutes.
- Webhooks: `POST /api/git/webhooks/{connection_id}`, body ≤ **1 MB**.
  - GitHub and Gitea: `X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the raw body>`.
  - GitLab: `X-Gitlab-Token` equals the secret.
  - Compare in constant time. A bad or missing signature gives 401. A connection without a secret gives 404.
  - The payload is used only to find which pull requests to refresh; their state always comes from the API.
- **The merge is the approval** (WF-6a "until a person approves the PR/MR in the git host"). A person merges in the git host, and an approving review alone is shown but does not finish the task. That matches the owner's choice that humans merge pull requests.
- Done stage (WF-6a, GIT-3/4), while a workflow waits on `human_code_review`:
  - tracked PR becomes `merged` → `finish_workflow`, event `pr.merged`, audit `git.pr_merged`;
  - tracked PR becomes `closed` → `escalate(wf, "pr_closed")`; `accept` finishes, `retry` reruns Finish (a new pull request);
  - any status change → task event `pr.status {state, checks, review}` and `task.updated`.
- Plain git (GIT-2/4): when none of the project's repositories is github/gitlab/gitea, the `pull_request` option pushes the branch and reports `outcome="branch_pushed"` without `pr_url`. With human review on, a person clicks **Mark merged**.

**Notifications (NOT-1, NOT-2)**
- Kinds:

  | Kind | Sent to | When |
  |---|---|---|
  | `needs_you` | the task's agent owner and human assignee | a workflow starts waiting (question, design/plan approval, escalation, human code review) |
  | `needs_you` | the draft agent's owner | an agent-to-agent draft awaits approval |
  | `assigned` | the new assignee user, or the new agent's owner | a task is assigned |
  | `mentioned` | each mentioned user who can read the task | a comment mentions them |
  | `agent_offline` | the run's requester, the task's assignee user and watchers | a task run fails with `runner_disconnected` |
  | `question_waiting` | non-viewer members of the target project | a question becomes `needs_human`, or is still `queued` after **15 min** (once per question) |

- Fields: `title` ≤ 200, `body` ≤ 500, `link` ≤ 500 (an app path such as `/projects/PAY/board?task=PAY-1`), `task_id`, `project_id`, `read_at`.
- Rules:
  - Never notify the actor about their own action, or an inactive user.
  - Skip a new row when the same user, kind and task has an unread one from the last **10 min**.
  - A recipient who cannot read the task or question is dropped.
- Preferences are per user and per kind, `in_app` and `email`. Defaults: `in_app` is on for every kind; `email` is on for every kind except `question_waiting`.
- Email:
  - goes through the job `notify.email` with retries, and only when SMTP is configured;
  - subject `[MegooColab] {title}`;
  - plain-text body `{body}\n\n{PUBLIC_URL}{link}`;
  - a send failure never fails the action that caused it.
- Live: `Event(type="notification.created", user_id=…)`. The list API returns 50 per page, newest first.
- Mention syntax in comments: `@[Display Name](user:<uuid>)`, inserted by the picker and rendered as `@Display Name`.

**Admin (ADM-1, ADM-2, ADM-3)**
- New `org_settings` columns:
  - `dream_enabled` bool, default true;
  - `dream_hour_utc` 0–23 | null (null means the `MEMORY_DREAM_HOUR_UTC` setting);
  - `default_finishing_option` (default `pull_request`);
  - `default_require_human_code_review` (default false);
  - `default_sprints_enabled` (default true);
  - `default_commit_docs_to_repo` (default false).

  New projects take these values.
- Audit additions:
  - `agent_run.started` when a run is sent, with `{agent_id, task_id|question_id, role}`;
  - `agent_run.ended` with `{status, reason}`;
  - `git.connection.created|updated|deleted`;
  - `git.pr_merged`;
  - `notification.preferences_changed`.

**Installation (§4, §12)**
- The `LICENSE` file is Apache-2.0, the author's call in §4, which the owner confirms before merge. `NOTICE` keeps the superpowers MIT attribution.

## Review Focus

1. **Secrets leak or are forged.** A provider token or webhook secret could appear in an API response, error, log, audit entry or notification. A webhook with no signature or a wrong one could change a task. A webhook payload that claims "merged" could finish a task. *(Task 1 `test_token_never_returned_or_logged`, Task 2 `test_webhook_signature_rejected_and_payload_never_trusted`.)*
2. **Pull-request mismatches.** The wrong task could finish: a PR URL on another repository, another host, a malformed URL, or a URL in a repository the project does not own. Each must stay untracked. *(Task 2 `test_pr_url_matching_matrix`.)*
3. **Provider outages and rate limits.** A 401, 404, 429, timeout or garbage response must never mark a PR merged or closed, finish or escalate a workflow, or poll in a tight loop. The human button still works. *(Task 2 `test_poll_errors_keep_state_and_back_off`.)*
4. **Notification leaks.** A recipient could learn about a task, question or project they cannot read: mentioning an outsider, a question to a project they are not in, a deactivated user. *(Task 4 `test_recipients_filtered_by_access_and_status`, Task 5 `test_mention_of_outsider_ignored`.)*
5. **Notification floods.** Repeated nudges and escalations, the actor's own actions, a question waiting for hours, an email outage. Expect at most one unread row per user, kind and task per 10 minutes, one waiting notice per question, and no failed actions. *(Task 4 `test_dedupe_and_no_self_notify`, Task 5 `test_question_waiting_once`.)*

---

## File Structure

```
backend/app/git/
  models.py      GitConnection, TaskPullRequest
  providers.py   PrRef, PrStatus, parse_pr_url, repo_path, client per kind (fetch_pr, whoami), GitProviderError
  service.py     connections CRUD, match_pr, track_pr, refresh_pr, apply_status (Done-stage transitions)
  jobs.py        git.pr_poll, git.pr_refresh
  router.py      /api/admin/git-connections, /api/git/webhooks/{id}
  schemas.py
backend/app/notifications/
  models.py      Notification, NotificationPref
  service.py     notify, recipients helpers, preferences, mentions parsing
  jobs.py        notify.email, notify.questions_waiting
  router.py      /api/notifications…, /api/me/notification-preferences
  schemas.py
backend/app/workflow/{engine,finish}.py, methodology_texts/defaults/finish.md, methodology_history.py
backend/app/{org,projects,agent_runs,agents,a2a,memory,tasks}/…   hooks and settings
frontend/src/lib/{notifications,git}.ts
frontend/src/components/notifications/{NotificationBell,NotificationList,NotificationPrefs}.tsx
frontend/src/components/git/{GitConnections,PullRequestBadge}.tsx
frontend/src/app/(app)/{notifications,settings/notifications,admin/git}/page.tsx
frontend/e2e/{git,notifications}.spec.ts
docs/install.md, LICENSE, NOTICE
```

---

### Task 1: Git connections and provider clients

**Files:**
- Create: `backend/app/git/{__init__,models,providers,service,router,schemas}.py`, migration `git_connections`, `backend/tests/git/test_connections.py`, `backend/tests/git/test_providers.py`
- Modify: `backend/app/projects/{models,schemas,router}.py` (repository `connection_id`), `backend/app/main.py` (router), `backend/pyproject.toml` (move `httpx` to runtime deps)

**Interfaces:**
- Produces:
  - `GitConnection(id, name, kind, base_url, token_enc, webhook_secret_enc, created_by, timestamps)` and `ProjectRepository.connection_id`.
  - `providers.PrRef(kind, web_base, path, number)`.
  - `providers.PrStatus(state, checks, review, merged_at, head_sha)`.
  - `providers.parse_pr_url(url: str, conn: GitConnection) -> PrRef | None`.
  - `providers.repo_path(repo_url: str) -> str | None`, giving `owner/repo` or a nested GitLab path.
  - `async providers.fetch_pr(conn, ref, *, client: httpx.AsyncClient | None = None) -> PrStatus`.
  - `async providers.whoami(conn, *, client=None) -> str`, the login name.
  - `class GitProviderError(Exception): code` (one of the error codes in Global Constraints).
  - Endpoints:

    | Method and path | Purpose |
    |---|---|
    | `GET /api/admin/git-connections` | list |
    | `POST /api/admin/git-connections` | create |
    | `PATCH /api/admin/git-connections/{id}` | update |
    | `DELETE /api/admin/git-connections/{id}` | delete |
    | `POST /api/admin/git-connections/{id}/test` | `{ok, login | error}` |

    Repository create and patch accept `connection_id`; `RepoOut` adds `connection: {id, name} | null`.

- [ ] **Step 1: Write failing tests.** Provider tests use `httpx.MockTransport`; there is no network.
  - `test_parse_pr_url_shapes`: github.com, GitHub Enterprise with a path prefix, a nested GitLab group with `-/merge_requests/`, and gitea `/pulls/` parse. A different host, a missing number or `javascript:` gives `None`.
  - `test_repo_path_forms`: `https://h/o/r.git`, `git@h:o/r.git` and `ssh://git@h:22/g/sub/r` give `o/r` or `g/sub/r`.
  - `test_github_status_mapping`: merged; open with check runs failing, pending and success; and combined status with no runs gives `none`. The latest review per user wins.
  - `test_gitlab_status_mapping`: opened, merged and locked; `head_pipeline` null, failed and running; `approvals.approved`.
  - `test_gitea_status_mapping`.
  - `test_provider_errors_map_to_codes`: 401→`unauthorized`, 404→`not_found`, 429 or 403 with `X-RateLimit-Remaining: 0`→`rate_limited`, timeout→`unreachable`, non-JSON→`bad_response`.
  - `test_admin_crud_and_test_endpoint`: admins only (members get 403); duplicate name 409 `git_connection_name_taken`; `base_url` with credentials or a query gives 422; audits are written.
  - `test_token_never_returned_or_logged`: the token is absent from every response, error message, audit row and captured log (caplog).
  - `test_repository_connection_link`: a manager links a connection; a deleted connection leaves `connection: null`.
- [ ] **Step 2:** Run `uv run pytest tests/git -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement. Generate the migration against `megoo_migrate` (`DEV_DATABASE_URL=…/megoo_migrate bash scripts/makemigration.sh "git connections"`), with named constraints, and check a downgrade round trip.
- [ ] **Step 4:** Run `uv run pytest tests/git -q` and `uv run --with ruff ruff check app/git tests/git`. Expected: PASS, clean.
- [ ] **Step 5:** Commit: `feat(git): provider connections and clients`.

### Task 2: Pull-request tracking and the Done stage

**Files:**
- Create: `backend/app/git/jobs.py`, migration `task_pull_requests`, `backend/tests/git/test_tracking.py`, `backend/tests/git/test_webhooks.py`
- Modify:
  - `backend/app/git/{models,service,router}.py`
  - `backend/app/workflow/finish.py`: track on `report_finish`; `branch_pushed` for plain git; `ACCEPT_HANDLERS["pr_closed"]`
  - `backend/app/workflow/methodology_texts/defaults/finish.md`: plain git `branch_pushed`; Gitea/Forgejo `tea pulls create`
  - `backend/app/workflow/methodology_history.py`: append the new hash
  - `backend/app/worker.py`: register `app.git.jobs`
  - `backend/app/tasks/{schemas,service}.py`: `TaskOut.pull_request`

**Interfaces:**
- Consumes: Task 1 `parse_pr_url`, `repo_path`, `fetch_pr`, `GitProviderError`.
- Produces:
  - `TaskPullRequest(task_id PK, url, connection_id | None, state, checks, review, merged_at, head_sha, error, failures, next_check_at, last_checked_at)`.
  - `async service.match_pr(db, project_id, url) -> tuple[GitConnection, PrRef] | None`.
  - `async service.track_pr(db, task, url) -> TaskPullRequest`, which creates or replaces the row and queues `git.pr_refresh`.
  - `async service.refresh_pr(db, row) -> None`.
  - `async service.apply_status(db, row, status: PrStatus) -> None`, which applies the Done-stage transitions in Global Constraints.
  - Jobs `git.pr_poll` (periodic) and `git.pr_refresh {task_id}` (dedupe `git.pr_refresh:{task_id}`).
  - `TaskOut.pull_request: {url, state, checks, review, tracked: bool} | None`.
  - `WorkflowOut.pull_request` as above.
  - The finish outcome `branch_pushed`.

- [ ] **Step 1: Write failing tests**
  - `test_pr_url_matching_matrix`. Tracked only for a URL on the connection's base whose path equals a linked repository's path. Untracked:
    - a repository of the project with no connection;
    - another project's repository;
    - another host;
    - the same number in another repository;
    - a malformed URL.
  - `test_report_finish_tracks_pr_and_refresh_reaches_status`: `report_finish` with a tracked URL creates the row and queues a refresh. The refresh, using a mock transport, stores `open/pending/none`, records the `pr.status` event and publishes `task.updated`.
  - `test_merged_pr_finishes_waiting_workflow`: human review on, the workflow waits `human_code_review`, the PR becomes merged; the workflow is `finished`, with event `pr.merged`, audit `git.pr_merged`, and the card in the done column.
  - `test_closed_pr_escalates_and_accept_or_retry`: `pr_closed`; `accept` finishes; `retry` queues a Finish run.
  - `test_no_human_review_still_shows_status`: the workflow finished at `pr_opened`; the status updates; nothing else changes.
  - `test_poll_errors_keep_state_and_back_off`. For 401, 404, 429, a timeout and garbage:
    - the state is unchanged and the error code is stored;
    - `failures` increments and `next_check_at` is 2, 4, 8 … ≤ 60 min ahead;
    - the workflow is unchanged;
    - `approve_human_review` still finishes it.
  - `test_poll_picks_open_rows_oldest_first_limit_50`.
  - `test_plain_git_branch_pushed_and_mark_merged`: a project whose repositories are all `plain` reports `branch_pushed` without `pr_url` (accepted). A github project without `pr_url` gives 422 `pr_url_required`. With human review on, `human-review` finishes it.
  - `test_webhook_signature_rejected_and_payload_never_trusted`:
    - a missing or bad `X-Hub-Signature-256` gives 401, as does a wrong `X-Gitlab-Token`;
    - a connection without a secret gives 404, and a body over 1 MB gives 413;
    - a valid webhook saying `"merged": true` only queues a refresh, and the state stays what the API returns (open).
  - `test_webhook_refreshes_matching_rows_only`: a github `pull_request` event, a gitlab `merge_request` event and a gitea event each refresh the row whose number and repository path match.
  - `test_finish_text_names_branch_pushed_and_tea`, which also keeps `test_default_history_ends_with_the_current_texts` green.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement, and generate the migration as in Task 1. `apply_status` locks the task and workflow in the engine's order (`engine.lock_task`) before changing the workflow.
- [ ] **Step 4:** Run `uv run pytest tests/git tests/workflow -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(git): track pull requests and drive the Done stage`.

### Task 3: Admin settings, audit and agent overview

**Files:**
- Modify:
  - `backend/app/org/{models,router}.py`, plus a migration for the `org_settings` columns
  - `backend/app/projects/router.py`: defaults on create
  - `backend/app/memory/dream.py`: `dream_tick` reads `org_settings`
  - `backend/app/agent_runs/service.py`: audit the start in `_send_start` and `_send_answer_start`, and the end in `_transition`; `cancel_run` for answering runs
  - `backend/app/agents/service.py`: `admin_agents_out` shows answering runs
- Test: `backend/tests/org/test_admin_settings.py`, `backend/tests/agent_runs/test_audit_and_cancel.py`

**Interfaces:**
- Produces: `AdminSettingsOut` and `AdminSettingsIn` gain `dreaming: {enabled, hour_utc | null}` and `project_defaults: {finishing_option, require_human_code_review, sprints_enabled, commit_docs_to_repo}`; `AdminAgentOut.current` becomes `{kind: "task"|"question", ref, title} | None`.

- [ ] **Step 1: Write failing tests**
  - `test_settings_round_trip_and_validation`: `hour_utc` 24 gives 422; null falls back to the setting; the change is audited `org.settings_changed`.
  - `test_new_project_takes_org_defaults`; existing projects are unchanged.
  - `test_dream_tick_respects_enabled_and_hour`: disabled means nothing is queued; the org hour wins over the setting.
  - `test_agent_run_start_and_end_audited`: a task run and an answering run each give `agent_run.started` and `agent_run.ended` with status and reason.
  - `test_cancel_answering_run_by_owner_or_admin`: 200 rather than 500; others get 403.
  - `test_admin_agents_shows_answering_run`: `current.kind == "question"`, `ref == "QBB-Q1"`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement, and generate the migration.
- [ ] **Step 4:** Run `uv run pytest tests/org tests/agent_runs tests/agents tests/memory -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(admin): dreaming schedule, project defaults, run audit`.

### Task 4: Notifications core

**Files:**
- Create: `backend/app/notifications/{__init__,models,service,router,schemas,jobs}.py`, migration `notifications`, `backend/tests/notifications/test_core.py`
- Modify: `backend/app/main.py`, `backend/app/worker.py`, `backend/app/tasks/service.py` (the `assigned` trigger)

**Interfaces:**
- Produces:
  - `Kind` (StrEnum of the six kinds) and `DEFAULT_PREFS: dict[Kind, tuple[bool, bool]]`.
  - `async service.notify(db, user_ids, kind, *, title, body, link, task_id=None, project_id=None, actor_id=None) -> int`, returning the rows created. It applies the rules in Global Constraints and queues `notify.email`.
  - `async service.readable_by(db, user, *, task_id=None, project_id=None, question_id=None) -> bool`.
  - Endpoints:
    - `GET /api/notifications?unread=&before=`
    - `GET /api/notifications/unread-count`
    - `POST /api/notifications/{id}/read`
    - `POST /api/notifications/read-all`
    - `GET` and `PUT /api/me/notification-preferences`

- [ ] **Step 1: Write failing tests**
  - `test_assignment_notifies_assignee_not_actor`, including the owner of an agent assignee.
  - `test_dedupe_and_no_self_notify`.
  - `test_recipients_filtered_by_access_and_status`: an inactive user, a user without access to the project, and a viewer for `question_waiting` are all dropped.
  - `test_preferences_default_and_update`: the defaults match Global Constraints; turning in-app off creates no row; the change is audited.
  - `test_email_job_sends_via_outbox_and_survives_failure`: an outbox mailer gets subject `[MegooColab] …` and the body with `PUBLIC_URL`. With no SMTP, nothing is queued. A mailer that raises leaves the action committed and the job retries.
  - `test_list_read_and_unread_count`: newest first, 50 per page, other users' rows give 404, and `read-all` works.
  - `test_live_event_per_user`: `notification.created` has the `user_id`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement, and generate the migration.
- [ ] **Step 4:** Run `uv run pytest tests/notifications tests/tasks -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(notifications): notification centre, preferences and email`.

### Task 5: Notification triggers

**Files:**
- Modify:
  - `backend/app/workflow/engine.py`: `wait_for` becomes `async def wait_for(db, wf, needs)` and notifies `needs_you`; update all 11 callers in `engine.py`, `build.py`, `documents.py`, `finish.py` and `mcp_server/workflow_tools.py`
  - `backend/app/tasks/activity.py`: mentions on comment create
  - `backend/app/agent_runs/service.py`: `agent_offline` in `fail_disconnected_runs`
  - `backend/app/a2a/{service,routing}.py`: draft → `needs_you`; `needs_human` → `question_waiting`
  - `backend/app/notifications/jobs.py`: `notify.questions_waiting` periodic, 300 s
  - migration: `a2a_questions.waiting_notified_at`
- Test: `backend/tests/notifications/test_triggers.py`

**Interfaces:**
- Consumes: Task 4 `notify` and `readable_by`.
- Produces: `service.mentioned_user_ids(body_md) -> list[uuid.UUID]`, parsing `@\[[^\]\n]{1,200}\]\(user:([0-9a-f-]{36})\)`, deduped and capped at 20.

- [ ] **Step 1: Write failing tests**
  - `test_needs_you_for_each_wait`: a question, design approval, plan approval, escalation and human code review each notify the agent owner and human assignee with a link to the task. A second wait within 10 min is deduped.
  - `test_mention_notifies_readable_users` and `test_mention_of_outsider_ignored`.
  - `test_agent_offline_mid_task`: a runner disconnect notifies the requester, assignee and watchers once.
  - `test_a2a_draft_and_needs_human`.
  - `test_question_waiting_once`: still queued after 15 min means one notice and `waiting_notified_at` set; later ticks send nothing.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement, and generate the migration.
- [ ] **Step 4:** Run the whole backend suite with `uv run pytest -q`, because `wait_for` touches the engine. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(notifications): needs-you, mentions, agent offline, waiting questions`.

### Task 6: Frontend — notifications and mentions

**Files:**
- Create: `frontend/src/lib/notifications.ts`, `frontend/src/components/notifications/{NotificationBell,NotificationList,NotificationPrefs}.tsx` and tests, `frontend/src/app/(app)/notifications/page.tsx`, `frontend/src/app/(app)/settings/notifications/page.tsx`
- Modify:
  - `frontend/src/components/shell/Header.tsx`: the bell
  - `frontend/src/lib/realtime.ts`: `notification` events invalidate `["notifications"]`
  - `frontend/src/components/task/CommentBox.tsx`: the `@` picker over the project's users
  - `frontend/src/components/ui/Markdown.tsx`: render `user:` links as `@Name`, never as a link
  - `frontend/src/lib/errors.ts`
  - API types

- [ ] **Step 1: Write failing tests**
  - `NotificationBell shows unread count and marks read`
  - `NotificationList pages and links`
  - `NotificationPrefs toggles in-app and email per kind`
  - `CommentBox inserts a mention token from the picker`
  - `Markdown renders a mention as text, never a user: link`
  - `realtime notification events refresh the bell`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. The bell sits in the header with `aria-label="Notifications"`, and the count badge is hidden at 0.
- [ ] **Step 4:** Run `npm test`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): notifications and mentions`.

### Task 7: Frontend — git and admin

**Files:**
- Create: `frontend/src/lib/git.ts`, `frontend/src/components/git/{GitConnections,PullRequestBadge}.tsx` and tests, `frontend/src/app/(app)/admin/git/page.tsx`
- Modify:
  - `frontend/src/components/shell/Sidebar.tsx`: Admin → Git, Lucide `GitPullRequest`
  - `frontend/src/app/(app)/projects/[key]/settings/page.tsx`: the repository connection select
  - `frontend/src/components/workflow/WorkflowPanel.tsx`: the PR badge; "Approve PR" becomes "Mark merged"
  - `frontend/src/components/board/TaskCard.tsx`: the PR badge
  - `frontend/src/components/task/TaskView.tsx`: the branch and PR row (GIT-5)
  - `frontend/src/app/(app)/admin/settings/page.tsx`: the Dreaming and New-project-defaults sections
  - API types

- [ ] **Step 1: Write failing tests**
  - `GitConnections creates, tests and never shows the token`: the token field is write-only and placeholder `••••` appears when set.
  - `PullRequestBadge states and checks`: open, merged and closed, plus checks success, failure and pending, each with a text label (not colour alone).
  - `Repository connection select saves`.
  - `WorkflowPanel shows Mark merged while waiting on human code review`.
  - `Admin settings save dreaming and defaults`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): git connections, pull requests and admin settings`.

### Task 8: Plan 6 follow-ups

These are the deferred minors from Plan 6's final review.

**Files:**
- Modify: `backend/app/a2a/{service,routing,router}.py`, `backend/app/mcp_server/a2a_tools.py`, `frontend/src/components/questions/*`, `frontend/src/lib/realtime.ts`, `frontend/src/app/(app)/projects/[key]/layout.tsx` (an incoming-questions link with a count)
- Test: `backend/tests/a2a/test_followups.py`, frontend `Questions.test.tsx`

- [ ] **Step 1: Write failing tests**
  - `test_ask_does_not_hold_project_lock_during_suggestions`: the number is taken with `UPDATE … RETURNING`, and suggestions are computed after it.
  - `test_open_question_cap_holds_under_concurrency`: 21 concurrent asks create 20, using an advisory lock per user.
  - `test_task_run_token_reads_only_its_tasks_questions`: `get_question` and `withdraw_question` for another task's question give `question_not_found`.
  - `test_routing_does_not_double_book_a_slot`: two route passes on one free slot create one run (the agent row is locked during selection).
  - `test_question_out_kb_document_readable_flag`.
  - Frontend:
    - `Ask hidden for viewers and without task write`
    - `View in Knowledge Base only when readable`
    - `task questions refresh on task events`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest tests/a2a tests/mcp -q` and `npm test`. Expected: PASS.
- [ ] **Step 5:** Commit: `fix(a2a): plan 6 follow-ups`.

### Task 9: Installation guide and licence

**Files:**
- Create: `docs/install.md`, `LICENSE` (Apache-2.0), `NOTICE` (superpowers MIT attribution, from `methodology_texts/NOTICE.md`)
- Modify: `README.md` (a short install section linking `docs/install.md`), `deploy/.env.example` (comments for every variable), `deploy/docker-compose.yml` (`extra_hosts: ["host.docker.internal:host-gateway"]` on the backend and worker, for self-hosted git hosts on the same machine and for the e2e fake provider)

**`docs/install.md` sections, in this order:**
1. Requirements
2. Get the code
3. `.env` (every variable explained)
4. Start (`docker compose up -d --build`)
5. First run: the organization and admin
6. HTTPS and domains (Caddy)
7. Email (SMTP)
8. AI providers and models (Admin → AI)
9. Git connections and webhooks, per provider: the token scopes (GitHub fine-grained "Pull requests: read, Commit statuses: read, Checks: read"; GitLab `read_api`; Gitea `read:repository`) and the webhook URL `https://<host>/api/git/webhooks/<id>` with its secret
10. Notifications
11. Developers: install the runner and connect a first agent, a walkthrough aimed at "invitation to watching the agent work in under 30 minutes" (§12)
12. Upgrades
13. Backups and restore (`pg_dump`/`pg_restore` through `docker compose exec`, and the `uploads` volume)
14. Troubleshooting

- [ ] **Step 1:** Write the docs, `LICENSE` and `NOTICE`.
- [ ] **Step 2: Verify the guide by following it literally.**
  - In a fresh `git worktree` of the branch, run the guide's commands with a test `.env`. Use project name `megoo-install`, its own ports, and touch no other Docker project.
  - Check `GET /api/setup/status` gives 200 and first-run setup works.
  - Run the backup and restore commands on that stack.
  - Tear it down with `down -v`.
  - Expected: every command in the guide works as written; fix the guide where it does not.
- [ ] **Step 3:** Commit: `docs: installation guide, licence and notice`.

### Task 10: End-to-end

**Files:**
- Create: `frontend/e2e/git.spec.ts`, `frontend/e2e/notifications.spec.ts`, `frontend/e2e/helpers/fakeGit.ts`
- Modify: `README.md` (both e2e sections)

- [ ] **Step 1: Write the e2e specs** on a fresh stack. `fakeGit.ts` is a Node HTTP server on the host that serves the GitHub API under `/api/v3` (`/user`, `/repos/o/r/pulls/1`, `/commits/{sha}/status`, `/check-runs`, `/reviews`) with a mutable state.
  1. **git.spec**:
     1. An admin adds a github connection with `base_url` `http://host.docker.internal:<port>`, a token and a webhook secret; **Test** shows the login.
     2. The project's repository `http://host.docker.internal:<port>/o/r` is linked to it, and the project requires human code review.
     3. The fake agent workflow reaches Finish and reports `pr_url …/o/r/pull/1`. The task shows "PR open · checks pending" and waits.
     4. The fake server flips the PR to merged and sends a signed webhook. The task reaches Done by itself and shows "merged".
     5. A webhook with a bad signature gives 401.
     6. A second task's closed PR escalates `pr_closed`, and **Accept** finishes it.
  2. **notifications.spec**:
     1. User A assigns a task to B: B's bell shows 1, and the link opens the task.
     2. A mentions B with the picker: B gets a "mentioned" notification; an outsider mentioned by token gets nothing.
     3. The fake agent workflow waits for design approval: the agent owner gets "needs you".
     4. B turns off in-app notifications for `assigned`, and the next assignment shows nothing.
- [ ] **Step 2:** Run them on the stack. Expected: FAIL until everything is wired.
- [ ] **Step 3:** Fix what they expose, test-first in the module that owns the problem, as separate `fix(...)` commits.
- [ ] **Step 4:** Run `npx playwright test` (all specs) twice on fresh stacks, plus `uv run pytest -q`, `npm test` and `go test ./...`. Expected: PASS. Tear down with `down -v`, touching only `megoo-e2e`.
- [ ] **Step 5:** Commit: `test(e2e): git integration and notifications end to end`.

---

## Spec coverage (Plan 7)

| BRD item | Task |
|---|---|
| GIT-1 providers (GitHub, GitLab cloud and self-hosted, Gitea/Forgejo, plain git) | 1, 2 |
| GIT-2 pushing and PRs on the laptop with the developer's credentials; reviews in the git host; plain git pushes the branch | 2 (finish text, `branch_pushed`) |
| GIT-3 PR/MR status via a read-only token per project and/or webhooks, driving Done | 1, 2 |
| GIT-4 plain git: a human marks merged | 2, 7 |
| GIT-5 tasks show the branch and PR/MR | 2, 7 |
| NOT-1 in-app centre and email: needs you, assigned, mentions, agent offline, waiting questions | 4, 5, 6 |
| NOT-2 per-user preferences | 4, 6 |
| ADM-1 git provider connections, defaults for new projects, dreaming schedule | 1, 3, 7 |
| ADM-2 audit of agent sessions (the other listed actions were already audited) | 3 |
| ADM-3 agent overview: current work includes answering runs | 3 |
| WF-6a waits until a person approves the PR/MR in the git host | 2 |
| §4 / §12 install and configure from the docs alone; licence; attribution | 9 |
| Plan 6 final-review minors | 8 |
