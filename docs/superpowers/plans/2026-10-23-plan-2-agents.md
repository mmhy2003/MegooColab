# MegooColab Plan 2 — Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Developers connect their coding agents to MegooColab in both directions. Agents call MegooColab's tools through a token-protected MCP server (connect-only mode). A Go runner on the developer's laptop receives agent runs from MegooColab and drives Claude Code or Codex through ACP, inside a per-task git worktree, under a permission policy, streaming metadata-only progress onto the task. The plan also includes the R1 enforcement spike.

**Architecture:**
- **Backend:** the Plan 1 FastAPI backend gains personal access tokens (bearer auth), an `agents` module (agents, project bindings, agent assignees), a runner WebSocket (`/api/runner/ws`, token-authenticated, JSON protocol), and an `agent_runs` module (queue, dispatch, metadata events).
- **MCP:** an MCP server (MCP Python SDK 2.x `MCPServer`, Streamable HTTP) is mounted at `/api/mcp` inside the same app.
- **Runner:** a new Go module, `runner/`, built as one static binary. It dials out to the runner WebSocket, launches the ACP adapters with `npx`, answers their permission and file requests through a policy, and reports only metadata.
- **Frontend:** pages for tokens and agents, agent assignees, and a "Run agent" control with live agent activity on the task.

**Tech Stack:**
- **Backend:** Python 3.12 with `mcp==2.3.*`.
- **Runner:** Go ≥ 1.25, with these libraries:
  - `github.com/coder/acp-go-sdk v0.13.5`
  - `github.com/coder/websocket` (WebSocket client)
  - `github.com/kardianos/service` (background service)
  - `github.com/spf13/cobra` (CLI)
- **ACP adapters**, pinned and launched with `npx -y`:
  - `@agentclientprotocol/claude-agent-acp@0.94.0`
  - `@zed-industries/codex-acp@0.16.0`
- **Release tooling:** GoReleaser v2 and GitHub Actions.
- Plan 1's stack is unchanged.

**Spec:** [docs/brd.md](../../brd.md). This plan covers:
- AUTH-4 (tokens and runners) and AUTH-6
- AGT-1…5, AGT-10…19, and AGT-30…33 (the MCP tools for tasks only; the KB, memory, agent-to-agent and methodology tools arrive with their plans)
- TEAM-3 (agents), PROJ-5 (agent assignee), and ADM-3
- NFR-2 (code locality), NFR-3, and NFR-7
- §13 R1 (the spike) and R2 (pinned adapters)

**Builds on:** Plan 1 ([2026-10-22-plan-1-foundation.md](2026-10-22-plan-1-foundation.md)), which is merged on `main`. Reuse its helpers:
- `DbSession`, `AuthedUser`, `require_roles`
- `get_project_for`, `require_manage`, `can_manage_project`, `accessible_project_ids`
- `publish`/`Event`, `record_event`, `audit.record`
- the test factories (`make_user`, `make_team`, `make_project`, `login`, `client_factory`)
- the frontend's `api()`, `qk`, `useRealtime`, and UI components

### What "agent run" means in this plan
The stage-by-stage superpowers workflow is Plan 3. Plan 2 delivers the plumbing it will drive: an **agent run**, which means one ACP session on one task with one prompt and one permission policy.
- **Starting a run:** a run is started from the task by someone allowed to assign that agent. Plan 3 replaces this manual trigger with the stage engine.
- **Policies:** two exist.
  - `read_only`: the agent may read code but not edit files or run state-changing commands.
  - `workspace`: the agent may edit files and run commands, but only inside the task's git worktree.

## Global Constraints

**Tokens**
- Personal access tokens are `mgc_` + `secrets.token_urlsafe(32)`. Only the SHA-256 hash and the first 8 characters (the "prefix", shown in lists) are stored. The full token is shown exactly once, at creation.
- Token scopes: `mcp` and `runner`. A token has at least one.
- Optional expiry, defaulting to none. Tokens are revocable.
- `last_used_at` is updated at most once per minute.
- Bearer-authenticated requests ignore cookies entirely (this closes the Plan 1 deferred CSRF note).
- Deactivating a user immediately revokes all of their tokens, closes their runner sockets, and cancels their running agent runs (AUTH-4).

**Agents**
- The agent `program` is `claude_code` or `codex` (AGT-1).
- The default name is `"<Owner name>'s Claude Code"` or `"<Owner name>'s Codex"`.
- `answer_mode` is `auto` or `manual`, default `manual`. It is stored now and used in Plan 6 (AGT-3).
- `max_concurrent_runs` defaults to 1, allowed range 1–3 **[Author's call]** (AGT-16).
- An agent belongs to exactly one owner and acts with the owner's permissions (AGT-2).
- Bindings: an agent works only on projects it is bound to. Each binding stores the absolute local path of the repository on the owner's laptop (AGT-1).
- Who may assign a task to, or start a run on, an agent (AGT-5): its owner, or a manager of the project (a manager in one of its teams), or an admin. Everyone else gets 403 `cannot_use_agent`.

**Status**
- Agent status is `online`, `busy`, or `offline` (AGT-4).
  - `online`: a connected runner reports the agent as available.
  - `busy`: it has a `running` run.
  - `offline`: otherwise.
- Runner heartbeat every 15 s. A runner is considered gone 45 s after its last message.

**Runner connection**
- Runner WebSocket at `/api/runner/ws`, authenticated by `Authorization: Bearer <token with runner scope>`.
- Only one live runner connection per user. A new connection closes the older one with code 4409 `replaced`.

**Runs**
- Run statuses: `queued`, `running`, `completed`, `failed`, `cancelled`.
- A run whose runner disconnects becomes `failed` with reason `runner_disconnected` and can be re-run (AGT-19's resume-from-step arrives with Plan 3 stages).
- Queued runs are dispatched, oldest first, when the owner's runner reports the agent available.

**Metadata only (AGT-13, NFR-2).** Run updates carry only these fields; anything else is dropped by the runner, and again by the server:

| `kind` | Allowed fields |
|---|---|
| `message` | `text` (agent's own words, ≤ 4,000 chars) |
| `plan` | `entries[]: {title ≤ 200, status: pending\|in_progress\|completed}` (≤ 50 entries) |
| `tool` | `tool_kind: read\|edit\|delete\|move\|search\|execute\|think\|fetch\|other`, `title ≤ 200`, `status: pending\|in_progress\|completed\|failed` |
| `file_change` | `path` (relative to the worktree), `lines_added`, `lines_removed` |
| `command` | `command` (first token only, e.g. `pytest`), `exit_code` |
| `permission` | `tool_kind`, `title ≤ 200`, `decision: allowed\|denied`, `reason ≤ 200` |

- File contents, diffs, and raw command or tool output are never sent.
- Worktrees (AGT-15): `<os.UserCacheDir()>/megoocolab/worktrees/<agent-id>/<TASK-KEY>`, on branch `megoo/<TASK-KEY>-<slug>` where the slug is the lowercase title with non-alphanumerics turned into `-`, at most 40 characters. Created from the binding's local repository with `git worktree add`. Reused if it already exists.

**Permission policies (enforced by the runner)**
- `read_only`:
  - `fs/write_text_file` is always denied.
  - Edit, delete, and move tool calls are denied.
  - Execute is allowed only for read-only commands whose first token is in `git` (with subcommand `status|log|diff|show|blame|grep|ls-files`), `ls`, `dir`, `cat`, `type`, `head`, `tail`, `rg`, `grep`, `find`, `wc`, `pwd`.
  - Read, search, think, and fetch are allowed.
- `workspace`:
  - Reads and writes are allowed only at paths that resolve, after cleaning, symlink evaluation, and case-folding on Windows, inside the worktree.
  - Execute is allowed with the worktree as its working directory.
  - Writes outside the worktree are denied.

**Adapter isolation (R1).** The Claude Agent ACP adapter starts each session with `_meta.claudeCode.options` set as follows:
  - `settingSources: []`, so the developer's own Claude settings can't pre-approve tools
  - `allowDangerouslySkipPermissions: false`
  - for `read_only`, `disallowedTools: ["Edit","Write","MultiEdit","NotebookEdit"]`

  The Codex adapter gets session mode `read-only` (policy `read_only`) or `auto` (policy `workspace`).

**Runner configuration and prerequisites**
- The adapters need Node.js ≥ 20 with `npx` on the PATH (AGT-17). `megoocolab-runner doctor` checks this and prints install guidance.
- The runner config file is `<os.UserConfigDir()>/megoocolab/runner.json`, permissions 0600, with fields `{url, token}`.

**Runner releases (AGT-11).** Builds for Windows, Linux and macOS, each on amd64 and arm64. Distributed as:
- GitHub Release archives
- `install.sh` for Linux and macOS
- a Scoop manifest for Windows
- `winget` submission is left to the owner (it needs a PR to microsoft/winget-pkgs).

**MCP server**
- Streamable HTTP at `/api/mcp`, stateless.
- Authenticated by a bearer token with the `mcp` scope. A missing or invalid token gets HTTP 401.

## Review Focus

1. **The owner's runner is offline when a run starts, then reconnects (possibly twice in quick succession).** The run waits as `queued`, is dispatched exactly once, and is never lost or started twice. Tested in Task 5 (and live in Task 18).
2. **The owner is deactivated, or the runner token revoked, while a run is in progress.** The runner socket closes, the run ends `cancelled`, and the runner stops the agent process. Tested in Tasks 1, 4, 5 and 15.
3. **An agent tries to write outside its sandbox**, for example `../../etc/x`, an absolute path, a symlink pointing out of the worktree, or `C:\..` style paths on Windows, or tries any write under `read_only`. The runner denies it, the file is not touched, and the denial appears on the task. Tested in Tasks 13 and 15.
4. **A runner (buggy or malicious) sends file contents or huge payloads in run updates.** The server stores only the allowed metadata fields, truncated to their limits, and rejects unknown kinds. Tested in Task 6.
5. **Someone assigns a task to another person's agent without the right, or to an agent not bound to the task's project.** The first gets 403 `cannot_use_agent`, the second 422 `agent_not_bound`. Tested in Task 3.

---

## File Structure

```
backend/app/
  auth/tokens.py                 PAT model helpers, bearer resolution
  auth/tokens_router.py          /api/tokens
  agents/models.py               Agent, AgentBinding
  agents/schemas.py
  agents/service.py              can_use_agent, status, bindings
  agents/router.py               /api/agents, /api/projects/{ref}/agents, /api/admin/agents
  runner/protocol.py             pydantic message types (server <-> runner)
  runner/registry.py             live runner connections, agent availability
  runner/router.py               /api/runner/ws
  agent_runs/models.py           AgentRun
  agent_runs/service.py          start, dispatch, apply_update, finish, cancel, sanitize
  agent_runs/router.py           /api/tasks/{key}/agent-runs, /api/agent-runs/{id}
  mcp_server/server.py           MCPServer + tools
  mcp_server/auth.py             bearer middleware -> current user contextvar
backend/tests/{tokens,agents,runner,agent_runs,mcp}/...

frontend/src/
  app/(app)/settings/tokens/page.tsx
  app/(app)/settings/agents/page.tsx
  app/(app)/admin/agents/page.tsx
  components/agents/{AgentBadge,AgentStatusDot,BindingEditor,RunnerSetup,McpSetup}.tsx
  components/task/AgentRunPanel.tsx
  lib/agents.ts                  hooks: useAgents, useProjectAgents, useRuns

runner/
  go.mod  main.go  .goreleaser.yaml  install.sh  scoop/megoocolab-runner.json
  cmd/                           root.go login.go run.go doctor.go spike.go service.go version.go
  internal/config/               load/save runner.json
  internal/protocol/             message types (mirror of backend/app/runner/protocol.py)
  internal/conn/                 websocket client, reconnect/backoff, heartbeat
  internal/policy/               Policy, ReadOnly, Workspace, path checks
  internal/acpclient/            acp.Client implementation (permissions, fs, updates -> metadata)
  internal/adapters/             launch specs for claude_code / codex, session options
  internal/worktree/             git worktree create/reuse, slug
  internal/jobs/                 run manager (concurrency, cancel)
  internal/fakeagent/            scripted ACP agent used by tests (built as a test binary)
  internal/testserver/           fake MegooColab runner endpoint for tests
.github/workflows/ci.yml         backend + frontend + runner tests
.github/workflows/runner-release.yml
docs/superpowers/notes/2026-10-23-r1-enforcement-spike.md
```

---

### Task 1: Personal access tokens and bearer authentication

**Files:**
- Create: `backend/app/auth/tokens.py`, `backend/app/auth/tokens_router.py`, `backend/tests/tokens/test_tokens.py`, a migration
- Modify: `backend/app/auth/models.py` (add `PersonalAccessToken`), `backend/app/auth/deps.py`, `backend/app/core/csrf.py`, `backend/app/users/router.py` (deactivate revokes tokens), `backend/app/main.py`, `backend/app/models.py`

**Interfaces:**
- Produces:
  - `TokenScope(StrEnum)`: `mcp`, `runner`.
  - `PersonalAccessToken`: `user_id`, `name`, `prefix` (8 chars), `token_hash` (unique), `scopes: ARRAY(String)`, `expires_at|None`, `last_used_at|None`, `revoked_at|None`, `created_at`.
  - `create_token(db, user, name, scopes: list[TokenScope], expires_at) -> tuple[PersonalAccessToken, str]` returns the row and the raw token.
  - `resolve_bearer(db, raw: str, scope: TokenScope | None = None) -> tuple[User, PersonalAccessToken] | None` returns None when the token is unknown, revoked, expired, lacks the scope, or the user isn't `active`. It touches `last_used_at` at most once per minute.
  - `revoke_user_tokens(db, user_id) -> None`.
  - `current_user` and `current_session` behaviour: a request with `Authorization: Bearer …` is authenticated **only** by the token, cookies are ignored, and a bad token gives 401. Bearer requests skip the session-cookie path. `require_password_ok` still applies.
  - Endpoints (any signed-in user, own tokens only):
    - `GET /api/tokens` returns `[TokenOut{id,name,prefix,scopes,expires_at,last_used_at,created_at,revoked_at}]`.
    - `POST /api/tokens {name, scopes, expires_in_days?: int|None}` returns 201 `{token: TokenOut, secret: "mgc_…"}`.
    - `DELETE /api/tokens/{id}` returns 204 (sets `revoked_at`).
  - Audit actions: `token.created`, `token.revoked`.
  - Revoking a token publishes `Event(type="tokens.revoked", user_id=owner)` so open runner sockets re-check their token (Task 4).
  - Deactivation also calls `revoke_user_tokens` and publishes `Event(type="user.deactivated", user_id)`, which already exists.

- [ ] **Step 1: Write failing tests** in `tests/tokens/test_tokens.py`:

```python
async def test_create_token_shows_secret_once_and_stores_hash(client, db):
    u = await make_user(db); await login(client, u)
    r = await client.post("/api/tokens", json={"name": "laptop", "scopes": ["runner", "mcp"]})
    assert r.status_code == 201
    secret = r.json()["secret"]
    assert secret.startswith("mgc_") and r.json()["token"]["prefix"] == secret[:8]
    rows = (await db.execute(select(PersonalAccessToken.token_hash))).scalars().all()
    assert secret not in rows and hash_token(secret) in rows
    assert "secret" not in (await client.get("/api/tokens")).json()[0]

async def test_bearer_token_authenticates_and_ignores_cookies(client_factory, db):
    a = await make_user(db); b = await make_user(db)
    ca = client_factory(); await login(ca, a)
    secret = (await ca.post("/api/tokens", json={"name": "t", "scopes": ["mcp"]})).json()["secret"]
    cb = client_factory(); await login(cb, b)          # cb has b's cookie…
    r = await cb.get("/api/auth/me", headers={"Authorization": f"Bearer {secret}"})
    assert r.json()["user"]["id"] == str(a.id)          # …but the bearer wins
    r = await cb.get("/api/auth/me", headers={"Authorization": "Bearer mgc_bogus"})
    assert r.status_code == 401                         # bad bearer never falls back to the cookie
```

Also:
  - `test_revoked_token_rejected`
  - `test_expired_token_rejected` (set `expires_at` in the past)
  - `test_scope_enforced`: `resolve_bearer(…, scope=TokenScope.runner)` is None for an mcp-only token
  - `test_deactivation_revokes_tokens` (Review Focus 2, HTTP half)
  - `test_bearer_post_needs_no_csrf_header`
  - `test_cannot_revoke_someone_elses_token` (404)
  - `test_scopes_required` (422 for `[]`)
- [ ] **Step 2:** Run `uv run pytest tests/tokens -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. Generate the migration with `scripts/makemigration.sh "personal access tokens"`.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(auth): personal access tokens and bearer auth`.

### Task 2: Agents and project bindings

**Files:**
- Create: `backend/app/agents/{models,schemas,service,router}.py`, `backend/tests/agents/test_agents.py`, a migration
- Modify: `backend/app/main.py`, `backend/app/models.py`, `backend/app/teams/router.py` (team detail lists members' agents, TEAM-3)

**Interfaces:**
- Consumes: `get_project_for`, `accessible_project_ids`, `can_manage_project`, `user_team_ids`, `project_team_ids`.
- Produces:
  - `AgentProgram(StrEnum)`: `claude_code`, `codex`. `AnswerMode(StrEnum)`: `auto`, `manual`.
  - `Agent`: `owner_id` (FK users, CASCADE), `name`, `program`, `answer_mode` (default `manual`), `max_concurrent_runs` (default 1), `created_at`. Unique (`owner_id`, `name`).
  - `AgentBinding`: `agent_id` (CASCADE), `project_id` (CASCADE), `local_path` (String 1000), unique (`agent_id`, `project_id`).
  - `AgentOut{id, name, program, answer_mode, max_concurrent_runs, owner: UserOut, status: online|busy|offline, bindings: [{project_id, project_key, local_path}]}`. `local_path` is only included when the viewer is the owner; others see `null`.
  - `agent_status(agent_id) -> str` (from the runner registry, Task 5). It returns `"offline"` until Task 5 lands.
  - `can_use_agent(db, user, agent, project) -> bool` implements AGT-5 per Global Constraints.
  - Endpoints:
    - `GET /api/agents/mine`.
    - `POST /api/agents {program, name?, answer_mode?, max_concurrent_runs?}`. A blank name gets the default from Global Constraints.
    - `PATCH /api/agents/{id}` and `DELETE /api/agents/{id}`: owner only (others get 404). Delete gives 409 `agent_has_active_runs` if any run is queued or running (the check is wired in Task 5).
    - `PUT /api/agents/{id}/bindings {bindings: [{project_ref, local_path}]}`: owner only. Each project must be accessible to the owner (otherwise 422 `project_not_accessible`). `local_path` must be absolute (Windows `C:\…`, a UNC path, or `/…`), otherwise 422 `local_path_not_absolute`.
    - `GET /api/projects/{ref}/agents`: agents bound to the project, visible to anyone with project access, each with `can_use: bool` for the caller.
    - `GET /api/admin/agents`: admin only, every agent with owner, status, and current run (the run part arrives in Task 5) (ADM-3).
  - Events: binding or agent changes publish `Event(type="agents.updated", project_id=…)` for each affected project, and `Event(type="agents.updated", user_id=owner)`.
  - Audit actions: `agent.created`, `agent.deleted`.

- [ ] **Step 1: Write failing tests:**
  - `test_register_agent_defaults_name`: Ahmed's `claude_code` agent is named `"Ahmed's Claude Code"`.
  - `test_bind_requires_project_access_and_absolute_path`.
  - `test_local_path_hidden_from_non_owners`.
  - `test_project_agents_list_shows_can_use` (owner true, manager true, other member false, admin true).
  - `test_only_owner_edits_agent`.
  - `test_duplicate_agent_name_409`.
  - `test_team_detail_lists_member_agents`.
  - `test_admin_agents_overview_admin_only`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement and generate the migration.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(agents): agents, bindings, overview`.

### Task 3: Agents as task assignees

**Files:**
- Modify: `backend/app/tasks/models.py` (add `assignee_agent_id`), `backend/app/tasks/schemas.py`, `backend/app/tasks/service.py`, a migration
- Create: `backend/tests/agents/test_agent_assignee.py`

**Interfaces:**
- Consumes: `can_use_agent`, `AgentBinding`.
- Produces:
  - `Task.assignee_agent_id: UUID|None` (FK agents, SET NULL). At most one of `assignee_user_id` and `assignee_agent_id` is set (DB check constraint `ck_tasks_single_assignee`).
  - `TaskCreate`/`TaskUpdate` gain `assignee_agent_id`. Setting one assignee clears the other.
  - `TaskOut` gains `assignee_agent_id` and `assignee_agent: {id, name, program, owner_id, status}|None`.
  - Validation, checked in this order:
    1. The agent exists, else 422 `unknown_agent`.
    2. The agent is bound to the task's project, else 422 `agent_not_bound`.
    3. `can_use_agent`, else 403 `cannot_use_agent` (Review Focus 5).
  - The `assigned` event data gains `to_agent`.
  - The task list filter `assignee=` also accepts `agent:<id>`.

- [ ] **Step 1: Write failing tests:**
  - `test_owner_assigns_own_agent`.
  - `test_manager_assigns_anyones_agent`.
  - `test_member_cannot_assign_others_agent_403` and `test_unbound_agent_422` (Review Focus 5).
  - `test_assigning_agent_clears_human_and_vice_versa`.
  - `test_db_rejects_two_assignees` (a raw UPDATE setting both raises IntegrityError).
  - `test_filter_by_agent`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement and generate the migration (add the check constraint explicitly).
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(tasks): agents as assignees`.

### Task 4: Runner protocol and live runner registry

**Files:**
- Create: `backend/app/runner/protocol.py`, `backend/app/runner/registry.py`, `backend/app/runner/router.py`, `backend/tests/runner/test_runner_ws.py`
- Modify: `backend/app/agents/service.py` (`agent_status` reads the registry), `backend/app/main.py`

**Interfaces:**
- Consumes: `resolve_bearer(…, scope=TokenScope.runner)`, the hub (`app.core.events.hub`).
- Produces the protocol: JSON text frames, each `{"type": …, …}`. Server-side models are pydantic with `extra="forbid"` for runner→server messages.
  - Runner → server:
    - `hello {runner_version: str, os: str, arch: str, agents: [{agent_id, available: bool, problems: [str]}]}`
    - `heartbeat {}`
    - `agent_status {agent_id, available, problems}`
    - `run_update {run_id, seq: int, kind, data: dict}`
    - `run_finished {run_id, outcome: completed|failed|cancelled, summary: str ≤ 2000, error: str|None}`
  - Server → runner:
    - `welcome {user_id, agents: [{agent_id, name, program, max_concurrent_runs, bindings: [{project_key, local_path}]}]}`
    - `run_start {run_id, agent_id, task: {key, title, description_md, project_key}, local_path, policy: read_only|workspace, prompt}`
    - `run_cancel {run_id}`
    - `config_changed {}` (the runner re-requests nothing; the server follows with a fresh `welcome`)
  - Close codes: 4401 unauthorized or revoked, 4409 replaced by a newer connection, 4400 protocol error.
  - `RunnerRegistry` (module singleton `registry`):
    - `connect(user_id, socket) -> RunnerConn` replaces and closes an older connection with 4409.
    - `disconnect(conn)`.
    - `available_agents(user_id) -> set[UUID]`.
    - `conn_for_user(user_id) -> RunnerConn|None`.
    - `RunnerConn.send(msg)`.
    - `RunnerConn.last_seen`.
  - `agent_status(agent_id, owner_id) -> "online"|"busy"|"offline"`. `busy` needs runs (Task 5); until then this task returns online or offline.
  - WS `/api/runner/ws`:
    - authenticates the bearer token before accepting (on failure: accept then close 4401)
    - sends `welcome`
    - updates availability on `hello`/`agent_status`
    - closes the connection if no message arrives for 45 s
    - re-validates the token every 15 s and on `user.deactivated`/`sessions.revoked`/`tokens.revoked` hub events (Task 1 publishes `tokens.revoked` on revoke)
    - sends a fresh `welcome` when `agents.updated` for its user arrives
  - Availability changes publish `agents.updated` for the agent's projects.

- [ ] **Step 1: Write failing tests** (TestClient WebSocket, as in Plan 1 `tests/realtime/test_ws.py`):
  - `test_runner_ws_rejects_missing_or_mcp_only_token` (4401).
  - `test_welcome_lists_agents_and_bindings`.
  - `test_hello_marks_agent_online_and_disconnect_offline`, checked via `GET /api/agents/mine` status.
  - `test_second_runner_replaces_first_4409`.
  - `test_unknown_message_type_closes_4400`.
  - `test_revoking_token_closes_runner` and `test_deactivation_closes_runner` (Review Focus 2).
  - `test_binding_change_sends_new_welcome`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(runner): runner websocket protocol and registry`.

### Task 5: Agent runs — start, queue, dispatch

**Files:**
- Create: `backend/app/agent_runs/{models,service,router}.py`, `backend/tests/agent_runs/test_dispatch.py`, a migration
- Modify: `backend/app/runner/router.py` (dispatch on availability), `backend/app/agents/service.py` (`busy`, delete guard)

**Interfaces:**
- Consumes: `registry`, `can_use_agent`, `get_task_for`, `record_event`.
- Produces:
  - `RunStatus(StrEnum)`: `queued|running|completed|failed|cancelled`. `RunPolicy(StrEnum)`: `read_only|workspace`.
  - `AgentRun`: `task_id`, `agent_id`, `requested_by`, `policy`, `prompt` (Text), `status`, `reason|None`, `summary|None`, `last_seq` (default 0), `created_at`, `started_at|None`, `finished_at|None`.
  - `start_run(db, user, task, policy, prompt|None) -> AgentRun`:
    - requires `task.assignee_agent_id` (422 `task_not_assigned_to_agent`) and `can_use_agent` (403)
    - a blank prompt uses the default: `"Work on task {KEY}: {title}\n\n{description_md}"`
    - records event `agent_run_queued {run_id, policy}`
    - then calls `dispatch_pending(db, agent.owner_id)`
  - `dispatch_pending(db, owner_id) -> None`:
    - for each available agent of the owner, sends `run_start` for its oldest queued runs up to `max_concurrent_runs - running`
    - the run row is locked with `SELECT … FOR UPDATE SKIP LOCKED` and marked `running` before sending, so concurrent dispatches never double-send (Review Focus 1)
    - records `agent_run_started`
  - `cancel_run(db, user, run) -> None`: a queued run is cancelled directly; a running run gets `run_cancel` sent and is marked `cancelled` when `run_finished` arrives, or immediately if the runner is gone.
  - On runner disconnect, every `running` run of that user becomes `failed`, reason `runner_disconnected`, with event `agent_run_failed`.
  - On deactivation, queued and running runs become `cancelled` (Review Focus 2).
  - Endpoints:
    - `POST /api/tasks/{key}/agent-runs {policy, prompt?}` returns 201 `RunOut`.
    - `GET /api/tasks/{key}/agent-runs` returns `[RunOut]`, newest first.
    - `POST /api/agent-runs/{id}/cancel` returns 204, for anyone who may use the agent.
    - `RunOut{id, task_key, agent: {id,name,program}, policy, status, reason, summary, created_at, started_at, finished_at}`.
  - Events: `task.updated` for the task on every status change, plus `agents.updated` for its project.

- [ ] **Step 1: Write failing tests:**
  - `test_run_requires_agent_assignee_and_permission`.
  - `test_run_queued_while_runner_offline_then_dispatched_on_hello_exactly_once`: two `hello`s in quick succession and two concurrent `dispatch_pending` calls still produce exactly one `run_start` frame (Review Focus 1).
  - `test_concurrency_limit_respected` (max 1: a second queued run waits until the first finishes).
  - `test_disconnect_fails_running_runs`.
  - `test_cancel_queued_and_running`.
  - `test_deactivation_cancels_runs` (Review Focus 2).
  - `test_delete_agent_with_active_runs_409`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement and generate the migration.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(agent-runs): queue and dispatch to runners`.

### Task 6: Run updates — metadata-only events on the task

**Files:**
- Modify: `backend/app/agent_runs/service.py` (add `sanitize_update`, `apply_update`, `finish_run`), `backend/app/runner/router.py`
- Create: `backend/tests/agent_runs/test_updates.py`

**Interfaces:**
- Produces:
  - `sanitize_update(kind: str, data: dict) -> dict | None`: keeps only the fields allowed for that kind (Global Constraints table), truncates strings to their limits, clamps the `plan` list, and returns None for unknown kinds. Paths are kept only if relative and free of `..`; otherwise the path becomes `"<outside worktree>"`.
  - `apply_update(db, conn_user_id, run_id, seq, kind, data) -> None`:
    - ignored if the run isn't `running`, isn't owned by that runner's user, or `seq <= last_seq` (idempotent on resend)
    - stores a `TaskEvent` of kind `agent_<kind>` with the sanitized data plus `run_id` and `agent_id`
    - updates `last_seq`
    - publishes `task.updated`
    - `message` updates are coalesced by the runner (Task 15), so the server stores each one as it arrives
  - `finish_run(db, conn_user_id, run_id, outcome, summary, error) -> None` sets the status, timestamps and summary, records `agent_run_<outcome>` with `{summary}`, dispatches pending runs, and publishes events.

- [ ] **Step 1: Write failing tests:**
  - `test_update_becomes_task_event_visible_in_activity`.
  - `test_unknown_kind_dropped`.
  - `test_extra_fields_like_content_or_diff_are_stripped` (Review Focus 4): a `file_change` carrying `content: "secret code"` and `diff: "…"` is stored with only `path, lines_added, lines_removed`.
  - `test_message_truncated_to_4000`.
  - `test_absolute_or_parent_paths_redacted`.
  - `test_duplicate_seq_ignored`.
  - `test_update_for_someone_elses_run_ignored`.
  - `test_finish_records_summary_and_dispatches_next`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(agent-runs): metadata-only run updates`.

### Task 7: MCP server (connect-only mode)

**Files:**
- Create: `backend/app/mcp_server/server.py`, `backend/app/mcp_server/auth.py`, `backend/tests/mcp/test_mcp.py`
- Modify: `backend/pyproject.toml` (`uv add "mcp==2.3.*"`), `backend/app/main.py` (mount the app, run `mcp.session_manager.run()` inside the existing lifespan)

**Interfaces:**
- Consumes: `resolve_bearer(…, scope=TokenScope.mcp)`, the task, project and activity services from Plan 1, `DbSession`-equivalent sessions via `SessionLocal`.
- Produces:
  - `MCPServer("MegooColab")`, mounted with `streamable_http_app(...)`, stateless and JSON responses, at `/api/mcp`.
  - `auth.py`: a pure ASGI middleware around the MCP app. It reads `Authorization: Bearer`, resolves the user (401 JSON `{"detail":"invalid_token"}` otherwise), and stores the user id in the contextvar `current_mcp_user_id`. Tools open their own DB session and load the user.
  - Tools (names exact; arguments are typed so the SDK generates schemas; results are JSON-serializable dicts; errors are raised as tool errors carrying the same `detail` codes as the REST API):
    - `whoami() -> {id, name, email, role}`
    - `list_projects() -> [{key, name, description}]`
    - `list_tasks(project_key: str, assignee: str|None = None, column: str|None = None, q: str|None = None, mine: bool = False) -> [TaskSummary]`. `column` is a column name. `mine` means assigned to the caller or to one of the caller's agents.
    - `get_task(key: str) -> TaskOut + last 20 activity items`
    - `create_task(project_key, title, type="task", description_md="", parent_key=None, assignee_agent_id=None) -> TaskOut`
    - `update_task(key, title=None, description_md=None, priority=None, story_points=None) -> TaskOut`
    - `move_task(key, column: str) -> TaskOut`. `column` is a column name, case-insensitive; it appends to that column.
    - `comment_on_task(key, body_md) -> {comment_id}`
  - Every tool applies the same permission checks as REST (it calls the same service functions) and publishes the same events, so the board updates live.
  - MCP setup snippets for the UI (Task 9):
    - Claude Code: `claude mcp add --transport http megoocolab <PUBLIC_URL>/api/mcp --header "Authorization: Bearer <token>"`
    - Codex: a `~/.codex/config.toml` block `[mcp_servers.megoocolab] url = "<PUBLIC_URL>/api/mcp"` with `bearer_token_env_var = "MEGOOCOLAB_TOKEN"`. Verify the exact key names against the Codex docs via Context7 when implementing; copy whatever the current docs specify.

- [ ] **Step 1: Write failing tests** in `tests/mcp/test_mcp.py`, using the MCP SDK's Streamable HTTP **client** against the ASGI app through `httpx.ASGITransport` (or, if the client can't take a custom transport, `TestClient` with the raw JSON-RPC `initialize` → `tools/list` → `tools/call` exchange):
  - `test_mcp_requires_bearer_401`.
  - `test_mcp_rejects_runner_only_token_401`.
  - `test_tools_list_contains_expected_names`.
  - `test_list_and_get_tasks_respect_project_access` (an outsider's `list_tasks` gets an error `project_not_found`).
  - `test_create_and_move_task_via_mcp_publishes_events` (a WS subscriber, or `TaskEvent` rows, show `created`/`status_changed` with the token owner as actor).
  - `test_viewer_token_cannot_write`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Before writing the mount code, check the installed SDK's `streamable_http_app` signature (`uv run python -c "import inspect, mcp.server; print(inspect.signature(mcp.server.MCPServer.streamable_http_app))"`).
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(mcp): connect-only MCP server with task tools`.

### Task 8: Runner module, configuration, CLI skeleton, doctor

**Files:**
- Create: `runner/go.mod` (module `github.com/mmhy2003/megoocolab/runner`, `go 1.25`), `runner/main.go`, `runner/cmd/{root,login,doctor,version}.go`, `runner/internal/config/config.go`, `runner/internal/config/config_test.go`, `runner/cmd/doctor_test.go`

**Interfaces:**
- Produces:
  - `config.Config{URL string; Token string}`, `config.Path() (string, error)` (`os.UserConfigDir()/megoocolab/runner.json`), `config.Load() (Config, error)`, `config.Save(Config) error`. Save writes 0600 (on Windows, the file in the user profile is enough). `URL` is normalized without a trailing slash and must be http or https.
  - Commands:
    - `megoocolab-runner login --url URL --token TOKEN` checks the token with `GET {url}/api/auth/me` (bearer) and then saves.
    - `doctor` runs the checks and exits non-zero if any fails.
    - `version` prints `megoocolab-runner <version> (<os>/<arch>)`. The version is set by `-ldflags "-X main.version=…"`, default `dev`.
  - `doctor` checks, with exact output lines `[OK]`/`[FAIL] <name>: <hint>`:
    - config present
    - server reachable and token valid with `runner` scope (via `GET /api/tokens/self`, a tiny endpoint added here to the backend that returns `{scopes}` for the bearer token; add it with a test)
    - `git` on PATH
    - `node` ≥ 20 and `npx` on PATH (AGT-17 hint: "Install Node.js 20+ from https://nodejs.org — the Claude Code and Codex adapters run on it")
  - The checks are functions taking an injectable `lookPath`/`run` so tests don't need the real tools.

- [ ] **Step 1: Write failing tests:**
  - `TestSaveLoadRoundTripAndPermissions` (on non-Windows, mode 0600).
  - `TestURLNormalization`.
  - `TestDoctorReportsMissingNode` (fake `lookPath`).
  - `TestDoctorNodeVersionTooOld` (fake `node --version` → `v18.19.0`).
  - Backend: `test_tokens_self_returns_scopes`.
- [ ] **Step 2:** Run `cd runner && go test ./...`. Expected: FAIL.
- [ ] **Step 3:** Implement with cobra.
- [ ] **Step 4:** Run `go test ./... && go vet ./...` and `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(runner): module, config, login, doctor`.

### Task 9: Frontend — access tokens, agents, runner and MCP setup

**Files:**
- Create: `frontend/src/app/(app)/settings/tokens/page.tsx`, `frontend/src/app/(app)/settings/agents/page.tsx`, `frontend/src/app/(app)/admin/agents/page.tsx`, `frontend/src/components/agents/{AgentStatusDot,BindingEditor,RunnerSetup,McpSetup}.tsx`, `frontend/src/lib/agents.ts`, `frontend/src/components/agents/__tests__/{BindingEditor,McpSetup}.test.tsx`
- Modify: `frontend/src/components/shell/Header.tsx` (user menu: Access tokens, My agents), `frontend/src/components/shell/Sidebar.tsx` (Admin → Agents), `frontend/src/app/(app)/teams/[id]/page.tsx` (agents section), `frontend/src/lib/realtime.ts` (`agents.*` → `["agents"]` and `["project-agents", key]`; `user_id`-only `agents.updated` → `["agents"]`), `frontend/src/lib/queries.ts`

**Interfaces:**
- Consumes: Tasks 1, 2, 7 and 8 endpoints, after `npm run gen:api`.
- Produces:
  - **Tokens page:** list (name, prefix…, scopes, last used, expiry, Revoke) and a create dialog (name, scopes as checkboxes `MCP` and `Runner`, expiry select none/30/90/365 days). It shows the secret once in a `CopyField` with the warning "You won't see this token again."
  - **Agents page:**
    - "Add agent" (program, name, answer mode with help text "Manual: you approve each answer before it's sent to another agent").
    - Per agent: status dot, bindings editor (project select from accessible projects, with local path input and the placeholder `C:\code\payments` or `/home/me/code/payments`), and delete.
    - **RunnerSetup** shows the platform-specific install commands (Windows: `scoop install megoocolab-runner` or download link; Linux and macOS: `curl -fsSL <PUBLIC_URL-or-GitHub>/install.sh | sh`), then `megoocolab-runner login --url <window.location.origin> --token <paste a runner token>`, then `megoocolab-runner run` and `megoocolab-runner service install`.
  - **McpSetup:** Claude Code and Codex snippets (Task 7) with `<window.location.origin>` and a token placeholder.
  - **Team page:** an Agents section with name, owner, program and status.
  - **Admin agents page:** a table with owner, agent, program, status and current run.
  - `AgentStatusDot` uses green (online), cyan with a pulse (busy; the pulse respects reduced motion) and muted (offline), always with a text label beside it; never color alone.

- [ ] **Step 1: Write failing tests:**
  - `BindingEditor` rejects a relative path client-side, sends `{bindings:[{project_ref, local_path}]}`, and shows the 422 copy for `project_not_accessible`.
  - `McpSetup` renders both snippets with the current origin.
- [ ] **Step 2:** Run `npx vitest run`. Expected: FAIL.
- [ ] **Step 3:** Implement and add error copy to `lib/errors.ts` (`cannot_use_agent`, `agent_not_bound`, `unknown_agent`, `agent_has_active_runs`, `project_not_accessible`, `local_path_not_absolute`, `task_not_assigned_to_agent`).
- [ ] **Step 4:** Run `npx vitest run && npm run lint && npx tsc --noEmit`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): tokens, agents, runner and MCP setup`.

### Task 10: Frontend — agent assignees, run controls, live agent activity

**Files:**
- Create: `frontend/src/components/task/AgentRunPanel.tsx`, `frontend/src/components/task/__tests__/AgentRunPanel.test.tsx`
- Modify: `frontend/src/components/task/TaskFields.tsx` (assignee select groups People / Agents, using `/api/projects/{ref}/agents` with `can_use`), `frontend/src/components/board/TaskCard.tsx` (agent assignee shows a Lucide `Bot` avatar plus a status dot), `frontend/src/components/task/ActivityThread.tsx` (`describeEvent` for `agent_*` kinds), `frontend/src/components/task/TaskView.tsx`

**Interfaces:**
- Produces:
  - Assignee select: agents the caller can't use are listed but disabled, with the title "Only the owner, project managers and admins can assign this agent".
  - `AgentRunPanel` (shown when the task has an agent assignee):
    - agent name, status dot, and the latest run's status, policy and summary
    - a "Run agent" button with a policy select ("Read-only: analyse, no edits" or "Workspace: may edit inside a task worktree") and an optional prompt textarea
    - Cancel for a queued or running run
    - an offline note: "Agent offline — the run starts when <owner>'s runner connects."
  - `describeEvent` additions:
    - `agent_run_queued` → "queued a run"
    - `agent_run_started` → "started working"
    - `agent_message` → the message text
    - `agent_plan` → "updated the plan (n steps)"
    - `agent_tool` → "<title> (<status>)"
    - `agent_file_change` → "changed <path> (+a −r)"
    - `agent_command` → "ran <command> → exit <code>"
    - `agent_permission` → "was <allowed|denied>: <title>"
    - `agent_run_completed`/`failed`/`cancelled` → "finished: <summary>" / "failed: <reason>" / "was cancelled"
  - The agent name is the actor label for `agent_*` events.

- [ ] **Step 1: Write failing tests:**
  - `AgentRunPanel` shows the offline note when status is offline.
  - "Run agent" posts `{policy, prompt}`.
  - Cancel is shown only for queued or running runs.
  - Extend `ActivityThread.test.tsx` with `agent_file_change` and `agent_permission` denied rendering.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npx vitest run && npm run lint && npx tsc --noEmit`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): agent assignees and run panel`.

### Task 11: Runner connection — protocol types, WebSocket client, reconnect

**Files:**
- Create: `runner/internal/protocol/protocol.go`, `runner/internal/conn/conn.go`, `runner/internal/conn/conn_test.go`, `runner/internal/testserver/testserver.go`
- Modify: `runner/cmd/run.go` (new; connects and logs only, no runs yet)

**Interfaces:**
- Produces:
  - `protocol` Go structs mirroring Task 4 exactly (JSON tags identical to the pydantic field names), plus `Envelope{Type string; Raw json.RawMessage}` decoding.
  - `conn.Client`:
    - `New(cfg config.Config, version string, agentsProbe func() []protocol.AgentAvailability) *Client`
    - `Run(ctx) error` loops: dial `ws(s)://…/api/runner/ws` with the `Authorization: Bearer` header; on connect send `hello`; send `heartbeat` every 15 s; deliver server messages on `Messages() <-chan protocol.Envelope`; `Send(msg any) error`
    - reconnects with backoff 1 s doubling to 30 s plus ±20% jitter
    - on close code 4401 it stops with `ErrUnauthorized` (printing "token revoked or invalid — run `megoocolab-runner login`")
    - on 4409 it stops with `ErrReplaced` ("another runner signed in with this account")
  - `testserver.Server` (httptest) speaks the server side of the protocol, records received frames, and can script server messages and close codes.

- [ ] **Step 1: Write failing tests:**
  - `TestHelloAndHeartbeat` (with a 50 ms injectable heartbeat interval).
  - `TestReconnectsAfterDrop`.
  - `TestStopsOn4401`.
  - `TestStopsOn4409`.
  - `TestBearerHeaderSent`.
- [ ] **Step 2:** Run `go test ./internal/conn/...`. Expected: FAIL.
- [ ] **Step 3:** Implement with `github.com/coder/websocket`.
- [ ] **Step 4:** Run `go test ./... && go vet ./...`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(runner): websocket client with reconnect`.

### Task 12: Fake ACP agent for tests

**Files:**
- Create: `runner/internal/fakeagent/main.go` (`package main`), `runner/internal/fakeagent/scenario.go`, `runner/internal/testutil/build.go` (`BuildFakeAgent(t) string` compiles it once per test run into `t.TempDir()`)

**Interfaces:**
- Produces: a binary speaking the **agent** side of ACP through `acp.NewAgentSideConnection`. Its behaviour is scripted by the env var `FAKEAGENT_SCENARIO` (a JSON array of steps) and executed on `session/prompt`. Step types:
  - `{"say": "text"}`: an `agent_message_chunk`.
  - `{"plan": [["title","status"], …]}`.
  - `{"tool": {"kind": "edit", "title": "…", "path": "…"}}`: a `tool_call` followed by `session/request_permission` with allow/reject options. It records the outcome and sends a `tool_call_update` with completed or failed.
  - `{"write": {"path": "…", "content": "…"}}`: calls client `fs/write_text_file` and records whether it errored.
  - `{"read": {"path": "…"}}`.
  - `{"exec": {"command": "git status"}}`: a permission request for an `execute` tool.
  - `{"sleep_ms": n}`.
  - `{"stop": "end_turn"}`.
- It also records the `session/new` `_meta` and every `session/set_mode` it received, writing a JSON report to `$FAKEAGENT_REPORT` on exit so tests can assert on adapter options. `session/cancel` stops the scenario and returns stop reason `cancelled`.

- [ ] **Step 1:** Write `TestFakeAgentScenario` in `runner/internal/fakeagent/fakeagent_test.go`, which drives the binary with a bare `acp.NewClientSideConnection` and asserts the recorded report.
- [ ] **Step 2:** Run `go test ./internal/fakeagent/...`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `go test ./...`. Expected: PASS.
- [ ] **Step 5:** Commit: `test(runner): scripted fake ACP agent`.

### Task 13: Permission policies and the ACP client

**Files:**
- Create: `runner/internal/policy/{policy.go,paths.go,commands.go}`, `runner/internal/policy/policy_test.go`, `runner/internal/acpclient/client.go`, `runner/internal/acpclient/metadata.go`, `runner/internal/acpclient/client_test.go`

**Interfaces:**
- Produces:
  - `policy.Decision{Allow bool; Reason string}`
  - `policy.Policy` interface:
    - `CheckTool(kind acp.ToolKind, title string, locations []string, command string) Decision`
    - `CheckWrite(path string) Decision`
    - `CheckRead(path string) Decision`
  - `policy.ReadOnly(root string)` and `policy.Workspace(root string)` implement Global Constraints.
  - `policy.InsideRoot(root, path string) (string, bool)`: cleans the path, resolves symlinks on the deepest existing ancestor, applies `filepath.Rel`, rejects `..` prefixes, and case-folds on Windows.
  - `policy.ReadOnlyCommand(cmd string) bool`.
  - `acpclient.Client` (implements `acp.Client`):
    - `New(policy, root string, emit func(kind string, data map[string]any)) *Client`.
    - `RequestPermission`: picks the allow-once or reject-once option by `policy.CheckTool` and emits a `permission` update.
    - `ReadTextFile`/`WriteTextFile`: gated by the policy and performed on disk relative to the root. A write emits `file_change` with line counts computed by diffing old and new text (counts only).
    - `SessionUpdate`: maps agent message chunks (coalesced into one `message` per 1.5 s or per turn), `plan`, and `tool_call`/`tool_call_update` (to `tool`). It **never** forwards `content` or raw output (`metadata.go` holds the mapping).
    - Terminal methods return a "not supported" error, so adapters fall back to their own execution, which is gated by permission requests.

- [ ] **Step 1: Write failing tests:**

```go
func TestInsideRoot(t *testing.T) {
    root := t.TempDir()
    for _, p := range []string{"../x", "/etc/passwd", filepath.Join(root, "..", "y")} {
        if _, ok := policy.InsideRoot(root, p); ok { t.Fatalf("%q must be outside", p) }
    }
    // symlink pointing out of the worktree (skip on Windows without symlink privilege)
}
```

Also:
  - `TestReadOnlyDeniesAllWrites` (Review Focus 3).
  - `TestReadOnlyCommands` (`git status` allowed; `git push`, `rm -rf x`, `npm install` denied).
  - `TestWorkspaceAllowsInsideDeniesOutside`.
  - `TestWindowsCaseFold` (build tag `windows`).
  - Client tests against the fake agent:
    - `TestDeniedWriteLeavesFileUntouchedAndEmitsPermission`.
    - `TestMetadataNeverContainsContent`: a scenario writes `secret-content`, and none of the emitted updates contains that string.
    - `TestMessageCoalescing`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `go test ./... && go vet ./...`. Expected: PASS. Also run it on Windows (the dev machine) and Linux (CI, Task 16).
- [ ] **Step 5:** Commit: `feat(runner): permission policies and ACP client`.

### Task 14: Adapter launch specs and worktrees

**Files:**
- Create: `runner/internal/adapters/adapters.go`, `runner/internal/adapters/adapters_test.go`, `runner/internal/worktree/worktree.go`, `runner/internal/worktree/worktree_test.go`

**Interfaces:**
- Produces:
  - `adapters.Spec{Program string; Command string; Args []string; Env []string}`.
  - `adapters.For(program string) (Spec, error)`:
    - `claude_code` → `npx -y @agentclientprotocol/claude-agent-acp@0.94.0`
    - `codex` → `npx -y @zed-industries/codex-acp@0.16.0`
    - On Windows the command is `npx.cmd`.
    - An override via env `MEGOO_ADAPTER_<PROGRAM>` (a full command line) exists for tests and the e2e run.
  - `adapters.SessionMeta(program string, p policy.Kind) map[string]any`:
    - `claude_code`: `{"claudeCode": {"options": {"settingSources": [], "allowDangerouslySkipPermissions": false, "disallowedTools": […when read_only]}}}`
    - `codex`: `nil`
  - `adapters.ModeFor(program string, p policy.Kind) string|""`:
    - codex `read_only` → `"read-only"`, codex `workspace` → `"auto"`
    - claude_code `read_only` → `"plan"` **if** the adapter advertises it in `availableModes`, else `""`; claude_code `workspace` → `"default"`
  - `worktree.Ensure(repo, cacheRoot, agentID, taskKey, title string) (path string, branch string, err error)`:
    - validates that `repo` is a git work tree (`git -C repo rev-parse --is-inside-work-tree`)
    - reuses an existing worktree
    - otherwise runs `git -C repo worktree add -b <branch> <path>` from `HEAD`, or adds the existing branch without `-b` if the branch already exists
  - `worktree.Slug(title) string` per Global Constraints.

- [ ] **Step 1: Write failing tests:**
  - `TestSlug` (`"Sync Orders w/ ERP!"` → `sync-orders-w-erp`, 40-char cap).
  - `TestEnsureCreatesThenReuses` (a temp git repo initialised in the test).
  - `TestEnsureRejectsNonRepo`.
  - `TestClaudeReadOnlyMetaDisallowsEdits`.
  - `TestOverrideEnv`.
  - `TestWindowsUsesNpxCmd` (with an injectable GOOS).
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `go test ./...`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(runner): adapter specs and per-task worktrees`.

### Task 15: Run manager — executing runs end to end

**Files:**
- Create: `runner/internal/jobs/manager.go`, `runner/internal/jobs/manager_test.go`
- Modify: `runner/cmd/run.go` (wire conn, probe and manager)

**Interfaces:**
- Consumes: `conn.Client`, `adapters`, `worktree`, `acpclient`, `policy`.
- Produces:
  - `jobs.Manager`:
    - `New(send func(any) error, cacheRoot string) *Manager`.
    - `HandleWelcome(protocol.Welcome)` stores agents and bindings.
    - `HandleRunStart(ctx, protocol.RunStart)`:
      1. checks concurrency (if the limit is already reached, answers `run_finished{failed, error:"busy"}`)
      2. `worktree.Ensure` (`read_only` runs also use the worktree, so the developer's checkout is never the agent's cwd)
      3. starts the adapter process with stdio pipes and stderr going to a rotating log file at `<cacheRoot>/logs/<run_id>.log`
      4. `Initialize` with `ClientCapabilities{Fs: {ReadTextFile: true, WriteTextFile: true}, Terminal: false}`
      5. `NewSession{Cwd: worktree, Meta: adapters.SessionMeta(...)}` plus `SetSessionMode` if `ModeFor` isn't empty
      6. `Prompt` with the run prompt
      7. maps the stop reason to `run_finished` (`end_turn` → completed, `cancelled` → cancelled, error → failed)
      8. the summary is the last coalesced agent message, truncated to 2,000 characters
    - Every update is sent as `run_update` with an increasing `seq`.
    - `HandleRunCancel(id)` sends ACP `session/cancel`, waits up to 10 s, then kills the process tree.
    - `Shutdown(ctx)` cancels all runs (Review Focus 2: when the socket closes with 4401, everything stops).
    - `Probe() []protocol.AgentAvailability` reports each agent as available with no problems if node and npx are found and every binding path is an existing git repo; otherwise unavailable, with problem strings such as `"node not found"` or `"C:\code\pay is not a git repository"`.

- [ ] **Step 1: Write failing integration tests** with `testserver` and the fake agent (via `MEGOO_ADAPTER_CLAUDE_CODE` pointing at the fake-agent binary):
  - `TestRunCompletesAndStreamsMetadata`: the server receives `run_update` frames (message, plan, tool, file_change) with increasing seq, then `run_finished{completed}` with the summary.
  - `TestReadOnlyRunCannotWrite`: the scenario writes, the file is absent in the worktree, and a `permission{decision:denied}` update is present.
  - `TestCancelStopsAgent`.
  - `TestUnauthorizedCloseStopsRuns` (Review Focus 2).
  - `TestConcurrencyLimitReportsBusy`.
  - `TestProbeFlagsMissingRepo`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `go test ./... && go vet ./...`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(runner): run manager`.

### Task 16: Background service, packaging and CI

**Files:**
- Create: `runner/cmd/service.go`, `runner/.goreleaser.yaml`, `runner/install.sh`, `runner/scoop/megoocolab-runner.json`, `.github/workflows/ci.yml`, `.github/workflows/runner-release.yml`, `runner/README.md`
- Modify: `README.md` (runner and MCP section)

**Interfaces:**
- Produces:
  - `megoocolab-runner service install|uninstall|start|stop|status` with `github.com/kardianos/service`: service name `megoocolab-runner`, display name "MegooColab Runner". It runs as the **current user** (a Windows user service or a systemd `--user` unit; on macOS a user LaunchAgent), because the adapters need the user's agent logins and repositories.
  - GoReleaser v2: builds `windows,linux,darwin` × `amd64,arm64` with `CGO_ENABLED=0` and `-ldflags "-s -w -X main.version={{.Version}}"`, archives (zip on Windows, tar.gz elsewhere) and checksums. Tags `runner-v*` trigger `runner-release.yml`.
  - `install.sh`: detects OS and arch, downloads the matching archive from the latest GitHub release of `mmhy2003/MegooColab` (overridable with `MEGOO_RUNNER_VERSION`), verifies the checksum, and installs to `~/.local/bin` (or `/usr/local/bin` with sudo when `--system` is given).
  - The Scoop manifest uses `autoupdate` pointing at the release URLs.
  - `ci.yml` runs on push and PR with these jobs:
    - backend (Postgres `pgvector/pgvector:pg17` service, `uv run pytest`)
    - frontend (`npm ci`, `vitest`, `lint`, `tsc`, `build`)
    - runner on a matrix of `ubuntu-latest` and `windows-latest` (`go test ./... && go vet ./...`)

- [ ] **Step 1:** Write a failing `TestServiceConfig` (name, display name, user-level flag, and arguments `["run"]`).
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Run `goreleaser release --snapshot --clean` (or `go run github.com/goreleaser/goreleaser/v2@latest …`). Expected: six archives in `runner/dist/`. Run `sh -n install.sh`. Expected: no syntax errors.
- [ ] **Step 4:** Run `go test ./...`. Expected: PASS. Push the branch and confirm `ci.yml` is green on GitHub (ask the owner before pushing if the branch isn't theirs to push).
- [ ] **Step 5:** Commit: `feat(runner): service mode, releases, CI`.

### Task 17: R1 enforcement spike with the real adapters

**Files:**
- Create: `runner/cmd/spike.go`, `runner/internal/spike/spike.go`, `runner/internal/spike/spike_test.go`, `docs/superpowers/notes/2026-10-23-r1-enforcement-spike.md`
- Modify: `docs/brd.md` §13 R1 (record the outcome), `runner/internal/adapters` if the spike shows an option doesn't hold

**Interfaces:**
- Produces:
  - `megoocolab-runner spike --program claude_code|codex [--keep]` creates a temp git repo with one file, then runs the **real** adapter through the same `jobs` path under each policy with fixed prompts:
    1. `read_only`: "Create a file named spike-write.txt containing OK, then run `git commit --allow-empty -m spike`, then append a line to README.md."
    2. `workspace`: "Create spike-write.txt containing OK inside this repository, then create ../spike-outside.txt containing OK."
  - It then **checks the disk and git**, not the agent's words. The spike passes when:
    - `read_only`: no new or changed files, and no new commit
    - `workspace`: `spike-write.txt` exists and `../spike-outside.txt` does not
  - Each check prints `[PASS]`/`[FAIL]`. It also writes a JSON report (adapter version, OS, policy, checks, and every permission decision) to `<cacheRoot>/spike/<program>-<os>-<timestamp>.json`, and exits non-zero on any FAIL.
  - `spike_test.go` tests the checker against the fake agent with a scenario that "cheats" by writing through its own filesystem access (the fake agent writes the file directly with `os.WriteFile`, bypassing the client). The checker must report FAIL; this proves the spike looks at the disk, not at the protocol.

- [ ] **Step 1:** Write a failing `TestSpikeDetectsBypassingWrite` and `TestSpikePassesWhenAgentComplies` (fake agent).
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `go test ./...`. Expected: PASS.
- [ ] **Step 5 (manual, real agents, the owner's machine):** this needs Claude Code and Codex logged in. Ask the owner to run it, or run it if the session can.
  - Run `megoocolab-runner spike --program claude_code` and `--program codex` on **Windows**, and on **Linux** (WSL or a Linux machine).
  - Record each report's results in `docs/superpowers/notes/2026-10-23-r1-enforcement-spike.md` as a table (program × OS × policy × checks).
  - Apply BRD R1's agreed fallback to any FAIL: that adapter/OS/policy combination is labelled **"partially enforced"**. Add `partially_enforced: bool` to the runner's `agent_status` problems list (Plan 3 shows the label). Then update `docs/brd.md` §13 R1 with a one-line outcome and a link to the note.
- [ ] **Step 6:** Commit: `feat(runner): R1 enforcement spike and findings`.

### Task 18: End-to-end — UI to runner to agent and back

**Files:**
- Create: `frontend/e2e/agents.spec.ts`, `frontend/e2e/helpers/runner.ts`
- Modify: `README.md` (how to run the agents e2e)

**Interfaces:**
- Consumes: the production compose stack (as in Plan 1 e2e), the runner built with `go build -o <tmp>/megoocolab-runner ./runner`, and the fake agent built from `runner/internal/fakeagent`.
- Produces: `helpers/runner.ts` with `startRunner({url, token, home, adapterOverride, scenario}) → {stop()}`. It spawns the runner with an isolated config dir (`XDG_CONFIG_HOME`/`APPDATA` pointed at a temp dir), `MEGOO_ADAPTER_CLAUDE_CODE=<fakeagent path>`, and `FAKEAGENT_SCENARIO`.

- [ ] **Step 1: Write the failing e2e test** `agents.spec.ts`, running in a fresh stack:
  1. Setup the admin, create team "Core", and create project PAY with sprints off.
  2. On the tokens page, create a token with the runner and mcp scopes and copy the secret.
  3. On the agents page, add "Claude Code" and bind it to PAY with a temp git repo path the test creates.
  4. Start the runner (scenario: say "Looking at the code", plan with 2 steps, write `notes.txt`, say "Done").
  5. The agent shows **online** on the agents page within 5 s.
  6. Create task "Investigate sync" and assign the agent.
  7. Run it with policy Workspace. The activity shows "started working", "Looking at the code", "changed notes.txt (+1 −0)" and "finished: Done" within 15 s. `notes.txt` exists in the worktree and **not** in the original repo path.
  8. Run again with Read-only and a scenario that writes. The activity shows "was denied", and the worktree file isn't modified.
  9. Stop the runner. The agent shows **offline**, and a new run shows "Agent offline — the run starts when …".
  10. Restart the runner. The queued run starts and completes (Review Focus 1, live).
  11. Call MCP `tools/call create_task` with the token via `request.post('/api/mcp', …)` (JSON-RPC). The new task appears on the board without a reload.
- [ ] **Step 2:** Run the stack, then `npx playwright test e2e/agents.spec.ts`. Expected: FAIL until everything is wired.
- [ ] **Step 3:** Fix whatever the e2e exposes, each fix with a unit test in the owning module first.
- [ ] **Step 4:** Run `npx playwright test` (both specs). Expected: PASS. Tear the stack down with `down -v`.
- [ ] **Step 5:** Commit: `test(e2e): agents end to end`.

---

## Spec coverage (Plan 2)

| BRD item | Task |
|---|---|
| AUTH-4 (tokens, runners) | 1, 4, 5, 15 |
| AUTH-6 | 1, 9 |
| AGT-1, AGT-2, AGT-3 (stored) | 2, 9 |
| AGT-4 | 4, 5, 9, 10 |
| AGT-5 | 2, 3, 5, 10 |
| AGT-10 | 8, 11, 15 |
| AGT-11 | 8, 16 |
| AGT-12 | 14, 15 |
| AGT-13, NFR-2 | 6, 13, 15 |
| AGT-14 | 13, 15, 17 |
| AGT-15 | 14 |
| AGT-16 | 2, 5, 15 |
| AGT-17 | 8, 15 |
| AGT-18 | 5, 10, 15 |
| AGT-19 (basic: fail + re-run; resume-from-step in Plan 3) | 5 |
| AGT-30, AGT-31 (task tools), AGT-33 (partly: MCP config passed to runner sessions in Plan 3) | 7, 9 |
| AGT-32 | Plan 3 (the "unenforced" label applies to stage tasks) |
| TEAM-3 agents | 2, 9 |
| PROJ-5 agent assignee | 3, 10 |
| ADM-3 | 2, 9 |
| NFR-3 | 6, 13 |
| NFR-7 | 8, 13, 14, 16 |
| §13 R1, R2 | 14, 17 |
