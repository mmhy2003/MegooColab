# One Runner per Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agents link to one of their owner's runner tokens (their *machine*); a runner lights up, runs and cleans up only its own token's agents, and one person can have several machines online at once.

**Architecture:**
- `agents.runner_token_id` stores the link.
- The runner registry is keyed by token instead of by user. Every "find the agent's runner" lookup goes through the agent (its connection's welcome-owned agents) or through the run (the connection it was sent on).
- Run cleanup on hello and on disconnect is scoped to the connection's token. A startup sweep fails running runs of unlinked agents (left over from the upgrade).
- The frontend gets a Machine field, a "Not linked" hint, and linked agents on Access tokens.

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy/Alembic, pytest); Next 16 / React 19 / TanStack Query / vitest; Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-30-runner-machines-design.md`

## Global Constraints

- **Branch:** `feat/runner-machines` off `develop`, merged back into `develop`. No version bump and no release note in this plan; versions change only when the owner says "release".
- **No change to the runner program or the protocol:** `runner/` is untouched, and `Welcome`, `Hello` and the rest of `app/runner/protocol.py` keep their shapes.
- **Linking rules:** a token is linkable only when it is the agent owner's own, has the `runner` scope, and is neither revoked nor expired. Anything else → 422 `runner_token_invalid`. Unlinking (`null`) is always allowed.
- **Changing or removing a link while the agent has a run with status `running`** → 409 `agent_running`. Queued runs don't block.
- **Revoking unlinks.** Revoking a token clears `runner_token_id` on its agents, and `revoke_user_tokens` (password reset, deactivation) clears all of that user's agents. Both happen in the revoking transaction, and both publish `agents.updated` for the owner and the agents' bound projects. An expired token keeps its links.
- **`machine` on agent responses:** `{token_id, name, expired}`, set only when the viewer is the owner or an admin; `null` otherwise or when unlinked.
- **Copy, verbatim:**
  - select label `Machine`; option `Not linked`;
  - unlinked hint `Not linked to a machine — it stays offline until you pick its machine's token.`;
  - expired `Machine token expired — pick another`;
  - no runner tokens: `Create a token with the Runner scope in Access tokens first.` (the words "Access tokens" link to `/settings/tokens`);
  - machine name beside the status dot: `on {name}`;
  - errors (`lib/errors.ts`):
    - `agent_running`: `This agent is running a task. Wait for it to finish or cancel it first.`
    - `runner_token_invalid`: `Pick one of your runner tokens that hasn't expired or been revoked.`
  - Access tokens: column `Agents`; the revoke confirmation adds `{n} linked agent(s) will be unlinked and stay offline until you link them again.` (singular `agent` when n = 1, nothing added when n = 0);
  - reset page, appended to the success text: `Your access tokens were revoked too: create new ones for your runners and link your agents to them.`;
  - RunnerSetup: `Create one token per computer, and link each agent to the token of the computer it runs on.`
- **Working rules:**
  - Docker: only the `megoo-e2e` compose project and the dev containers.
  - Migrations are generated and checked against `megoo_migrate` only.
  - Never run two pytest runs at once.
  - Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **One user, two machines.** A run going on Yoga survives Legion connecting (hello), sending a stray `run_finished`, and disconnecting (Task 3 tests).
2. **A relinked agent with a queued run.** The run waits for the new machine and is never sent to the old one (Task 2 `test_queued_run_dispatches_to_linked_machine`).
3. **A token revoked while its runner works.** That machine's runs are cancelled with `runner_unauthorized`, its agents are unlinked, and the other machine is untouched (Task 3).
4. **`PATCH /api/agents/{id}` without `runner_token_id`** (renaming, answer mode) keeps the link. Only an explicit `null` unlinks (Task 1).
5. **A teammate looking at project agents** gets no `machine`, while the owner and an admin do (Task 1).

---

### Task 1: The link: data, API, revoke

**Files:**
- Modify:
  - `backend/app/agents/models.py`: `Agent.runner_token_id: Mapped[uuid.UUID | None]`, FK `personal_access_tokens.id`, `ondelete="SET NULL"`, indexed.
  - `backend/app/agents/schemas.py`:
    - `AgentIn.runner_token_id: uuid.UUID | None = None`;
    - `AgentPatch.runner_token_id: uuid.UUID | None = None`;
    - new `MachineOut(token_id: uuid.UUID, name: str, expired: bool)`;
    - `AgentOut.machine: MachineOut | None = None`.
  - `backend/app/agents/service.py`, `backend/app/agents/router.py` (create, update).
  - `backend/app/auth/tokens.py` (`revoke_token`, `revoke_user_tokens`).
  - `backend/app/auth/tokens_router.py`: `TokenOut.agents: list[TokenAgentOut] = []`, with `TokenAgentOut(id: uuid.UUID, name: str)`, filled in `list_tokens`.
- Create:
  - `backend/migrations/versions/<rev>_agent_runner_token.py`;
  - `backend/tests/agents/test_machines.py`.

**Interfaces:**
- Produces (`app/agents/service.py`):
  - `async def check_runner_token(db, owner_id: uuid.UUID, token_id: uuid.UUID) -> None`: raises 422 `runner_token_invalid` per Global Constraints.
  - `async def has_running_runs(db, agent_id: uuid.UUID) -> bool`.
  - `async def unlink_tokens(db, owner_id: uuid.UUID, token_ids: list[uuid.UUID] | None) -> None`: clears the links (`None` = every token of the owner) and publishes `agents.updated` for the owner and the affected agents' bound projects.
- `auth/tokens.py` calls `unlink_tokens` through a local import, because `agents.service` imports far more than `auth` may.
- `update_agent` treats the link as sent only when `"runner_token_id" in body.model_fields_set`. It validates the link only when it changes, and refuses with 409 `agent_running` when the agent `has_running_runs`. Audit data on create and update carries `runner_token_id`.

- [ ] **Step 1: Write the failing tests** in `tests/agents/test_machines.py`. Mint tokens with `POST /api/tokens`, and use names "Yoga" and "Legion".
  - `test_create_agent_linked_to_runner_token`: 201, `machine == {"token_id": yoga_id, "name": "Yoga", "expired": False}`.
  - `test_new_agent_is_unlinked_by_default`: `machine is None`.
  - `test_link_refuses_foreign_mcp_only_revoked_and_expired_tokens`: another user's runner token, own `mcp`-only token, own revoked token, and own token with `expires_at` set in the past in the DB. Each case → 422 `runner_token_invalid`, on both POST and PATCH.
  - `test_patch_without_runner_token_id_keeps_link`: PATCH `{"name": "Renamed"}` → machine unchanged. PATCH `{"runner_token_id": null}` → `machine is None`.
  - `test_relink_refused_while_agent_running`:
    - an `AgentRun(status="running")` inserted for the agent's task → PATCH to the Legion token → 409 `agent_running`, link unchanged;
    - the same with the run `queued` → 200.
  - `test_expired_token_keeps_link_and_reports_expired`: link, then expire the token in the DB → `machine.expired is True`.
  - `test_revoking_token_unlinks_only_its_agents`: `DELETE /api/tokens/{yoga}` → the Yoga agent has `machine is None`, the Legion agent is still linked.
  - `test_bulk_revoke_unlinks_every_agent`: `await revoke_user_tokens(db, me.id)`, commit → every agent of `me` is unlinked; another user's agent is untouched.
  - `test_machine_shown_only_to_owner_and_admin`:
    - for a teammate in the project: `GET /api/projects/PAY/agents` → `machine is None`;
    - for an admin: `GET /api/admin/agents` → `machine` set;
    - for the owner: `GET /api/agents/mine` → set.
  - `test_token_list_shows_linked_agents`: `GET /api/tokens` → Yoga's `agents == [{"id": ..., "name": ...}]` and Legion's `agents == []`.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/agents/test_machines.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement** the model, schemas, service functions and router changes.
  - Set `machine` in `_base_fields`: use one query for the agents' tokens, and set it only when `viewer.id == owner_id or viewer.role == Role.admin`.
  - Generate the migration against `megoo_migrate` (`alembic revision --autogenerate -m "agent runner token"`), and check `downgrade -1` / `upgrade head` there.
- [ ] **Step 4: Run** the same command, then `uv run pytest tests/agents tests/tokens tests/auth tests/core/test_migrations.py -q -p no:cacheprovider`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(agents): link an agent to its machine's runner token`.

### Task 2: One registry entry per token

**Files:**
- Modify:
  - `backend/app/runner/registry.py`, `backend/app/runner/router.py`;
  - `backend/app/agents/service.py` (`agent_statuses`, `agent_status`, `runner_info`, `agent_problems`, `_base_fields`);
  - `backend/app/agent_runs/service.py` (`_claim_next`, `dispatch_pending`, `cancel_run`, `stop_runs_before_delete`, `cancel_user_runs`);
  - `backend/app/a2a/routing.py` (`candidates`, `release_stale`, `route_and_dispatch`) and `backend/app/a2a/service.py` (the answering-run cancel);
  - `backend/app/dashboard/agents.py`, `backend/app/tasks/service.py`.
- Modify tests:
  - shared helpers: `tests/runner/test_runner_ws.py` (`_mint`, `_agent`) and `tests/agent_runs/test_dispatch.py` (`_fake_conn`);
  - every test that builds a `RunnerConn` or writes `registry._conns`.
- Create: `backend/tests/runner/test_machines_ws.py`.

**Interfaces:**
- Produces (`app/runner/registry.py`):
  - `RunnerConn(token_id: uuid.UUID, user_id: uuid.UUID, socket: WebSocket)`, with the new attribute `token_id`.
  - `RunnerRegistry`:
    - `async def connect(token_id, user_id, socket) -> RunnerConn`: replaces (4409) only a connection on the same token.
    - `def conn_for_token(token_id) -> RunnerConn | None`.
    - `def conns_for_user(user_id) -> list[RunnerConn]`.
    - `def conn_for_agent(agent_id) -> RunnerConn | None`: the live connection whose `owned_agents` holds it.
    - `def conn_for_run(run_id) -> RunnerConn | None`: the live connection whose `run_ids` holds it.
    - `def is_available(agent_id) -> bool`.
    - `def agent_supports(agent_id, capability: str) -> bool`.
    - `disconnect` and `connected_count` as today.
  - Removed: `conn_for_user`, `available_agents`, `supports`.
- Produces (`app/runner/router.py`):
  - `_authorize(raw) -> tuple[uuid.UUID, uuid.UUID] | None`, returning `(user_id, token_id)`.
  - `build_welcome(user_id: uuid.UUID, token_id: uuid.UUID) -> Welcome`: selects only agents with `runner_token_id == token_id`.
- Produces (`app/agents/service.py`):
  - `agent_statuses(db, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]`;
  - `agent_status(db, agent_id)`;
  - `runner_info(agent_id: uuid.UUID) -> RunnerInfo | None`;
  - `agent_problems(agent_id, owner_id, viewer)`, now reading `conn_for_agent`.
- Call sites:
  - Cancels use `conn_for_run`. In `cancel_user_runs`, a found connection gets `run_cancel`, and a run whose owner isn't the deactivated user stays running.
  - Capability checks use `agent_supports`.
  - Availability uses `is_available`.
  - `dispatch_pending(db, owner_id)` loops over `conns_for_user(owner_id)`.
  - `route_and_dispatch` skips owners with no connections.
- Test helpers:
  - `_mint` stores the new token's id on the `TestClient` as `tc.runner_token_id` when its scopes include `runner`.
  - `_agent` defaults `runner_token_id` to `getattr(tc, "runner_token_id", None)`.
  - `_fake_conn` builds `RunnerConn(uuid.uuid4(), user.id, socket)`, sets `owned_agents` as well as availability, and stores it under `conn.token_id`.
  - A test that creates its agent before minting its token links it with PATCH.

- [ ] **Step 1: Write the failing tests** in `tests/runner/test_machines_ws.py`. One user has tokens Yoga and Legion; agent A is linked to Yoga, B to Legion, C is unlinked.
  - `test_runner_is_sent_only_its_tokens_agents`: connect with Legion → the welcome's `agents` ids are `[B]`.
  - `test_two_machines_online_at_once`:
    - both connect and report every agent available → A and B `online`, C `offline`;
    - neither socket is closed.
  - `test_same_token_twice_still_replaces`: a second Yoga connection → the first closes with 4409.
  - `test_unlinked_agent_stays_offline`: a hello reporting C available → C stays `offline`.
  - `test_relinking_moves_agent_between_runners`:
    - both connected; PATCH A to Legion;
    - Yoga receives `config_changed`, then a welcome without A;
    - Legion receives one with A.
  - `test_queued_run_dispatches_to_linked_machine`:
    - A's task run is queued while only Legion is connected (reporting A available) → Legion receives no `run_start`;
    - Yoga connects and reports A available → Yoga receives `run_start` for it.
  - `test_runner_info_is_the_agents_own_machine`:
    - Yoga's hello says `0.1.0`, Legion's `0.2.0`;
    - `GET /api/agents/mine` → A `runner.version == "0.1.0"`, B `"0.2.0"`, C `runner is None`.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/runner/test_machines_ws.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement** the registry, the socket (`connect(token_id, user_id, …)`, `build_welcome(conn.user_id, conn.token_id)`) and every call site above. Then update the shared test helpers and the tests that touch `RunnerConn` or `registry._conns`.
- [ ] **Step 4: Run** the same command, then the whole backend suite: `uv run pytest -q -p no:cacheprovider`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(runner): one connection per token; agents follow their machine`.

### Task 3: Runs stay with their machine

**Files:**
- Modify:
  - `backend/app/agent_runs/service.py` (`fail_disconnected_runs`, `fail_unclaimed_runs`, new `fail_orphaned_runs`);
  - `backend/app/runner/router.py` (`_handle`: a run message passes only when the run's agent is linked to `conn.token_id`);
  - `backend/app/main.py` (lifespan).
- Create: `backend/tests/agent_runs/test_machine_runs.py`.

**Interfaces:**
- Consumes: Task 2's `RunnerConn.token_id`, `conn_for_token`; Task 1's `Agent.runner_token_id`.
- `fail_disconnected_runs`:
  - `superseded = registry.conn_for_token(conn.token_id) is not None`;
  - runs are selected by `Agent.owner_id == conn.user_id` and `or_(Agent.runner_token_id == conn.token_id, AgentRun.id.in_(conn.run_ids))`. The `run_ids` arm covers a revoke, where the link is cleared before the socket closes.
- `fail_unclaimed_runs`: selects by `Agent.runner_token_id == conn.token_id`.
- `async def fail_orphaned_runs(db) -> None`: running runs whose agent has `runner_token_id IS NULL` become `failed` with reason `runner_disconnected` (or `cancelled` with their actor if `cancelled_by` is set), through `_lock_runs_one_by_one` and `_transition`.
  - The lifespan calls it, and commits, right after `ensure_core_entities`.
  - *Ruling:* the spec puts this in the migration; a startup sweep does the same job while keeping the runs' normal events and notifications.
- `_handle`: a `RunUpdate` or `RunFinished` whose run's agent isn't linked to `conn.token_id` is ignored and not treated as a protocol error. One DB check runs in the `_run_message` session. `finish_run` and `apply_update` keep their signatures.

- [ ] **Step 1: Write the failing tests** in `tests/agent_runs/test_machine_runs.py`, with the same user, tokens and agents as Task 2. A run R is dispatched to Yoga for A's task.
  - `test_other_machine_hello_does_not_fail_runs`: Legion connects and says hello → R still `running`.
  - `test_other_machine_disconnect_leaves_runs_alone`: Legion connects, then disconnects → R still `running`.
  - `test_run_message_from_wrong_machine_is_ignored`: Legion sends `run_finished` for R → R still `running` and Legion's socket stays open.
  - `test_revoking_a_machine_token_cancels_its_runs_only`:
    - R on Yoga and R2 on Legion (B's task);
    - `DELETE /api/tokens/{yoga}` → Yoga closes with 4401;
    - R becomes `cancelled` with reason `runner_unauthorized`, R2 stays `running`;
    - A has `machine is None`.
  - `test_startup_sweep_fails_running_runs_of_unlinked_agents`:
    - a running run on C (unlinked) and one on A (linked);
    - `await fail_orphaned_runs(db)` → C's run is `failed` with `runner_disconnected`, A's is still `running`.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/agent_runs/test_machine_runs.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement** the three functions, the `_handle` guard and the lifespan call.
- [ ] **Step 4: Run** the same command, then the whole backend suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(runs): runs stay with the machine they were sent to`.

### Task 4: Frontend

**Files:**
- Create: `frontend/src/components/agents/MachineField.tsx`, `frontend/src/components/agents/__tests__/MachineField.test.tsx`.
- Modify:
  - `frontend/src/lib/api-types.ts` (`npm run gen:api`) and `frontend/src/lib/types.ts` (`Machine = S["MachineOut"]`);
  - `frontend/src/lib/errors.ts`;
  - `frontend/src/app/(app)/settings/agents/page.tsx`: Machine in `AddAgentDialog` and on `AgentCard`, saved with PATCH; `on {name}` beside the dot;
  - `frontend/src/app/(app)/admin/agents/page.tsx` (`on {name}`);
  - `frontend/src/app/(app)/settings/tokens/page.tsx` (`Agents` column, revoke text);
  - `frontend/src/app/(auth)/reset/[token]/page.tsx`;
  - `frontend/src/components/agents/RunnerSetup.tsx`.

**Interfaces:**
- `MachineField({ machine, tokens, value, onChange }: { machine: Machine | null; tokens: AccessToken[]; value: string | null; onChange: (tokenId: string | null) => void })`.
  - It lists `tokens` filtered to `runner` scope, not revoked and not expired, plus `Not linked` (value `null`).
  - It shows the hint for an unlinked agent, the expired text when `machine?.expired`, and the no-token text when the filtered list is empty.
  - The page reads tokens with the existing `qk.tokens()` query.

- [ ] **Step 1: Write the failing tests** in `MachineField.test.tsx`, plus a tokens page test (`src/app/(app)/settings/tokens/__tests__/page.test.tsx`, mocking `api`):
  - `lists only usable runner tokens`: an mcp-only, a revoked, an expired and a good runner token → the options are `Not linked` and the good one.
  - `shows the not-linked hint`.
  - `shows the expired text`.
  - `points to Access tokens when there is no runner token`: the link `href` is `/settings/tokens`.
  - `reports the picked token`: `onChange` is called with its id.
  - Tokens page:
    - the `Agents` column shows the linked names;
    - revoking a token with 2 agents asks with `2 linked agents will be unlinked and stay offline until you link them again.`
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/agents/__tests__/MachineField.test.tsx "src/app/(app)/settings/tokens"`. Expected: FAIL.
- [ ] **Step 3: Implement**: regenerate the API types, then the component and the page changes, using the copy in Global Constraints.
- [ ] **Step 4: Run** `cd frontend && npx vitest run && npm run lint && npx tsc --noEmit`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(web): pick each agent's machine`.

### Task 5: Docs, e2e and the whole branch

**Files:**
- Modify: `docs/install.md` (runner section), `runner/README.md` (login section): one token per computer, then link each agent to it on My agents.
- Modify the e2e specs that start a runner:
  - `frontend/e2e/agents.spec.ts`: through the UI, pick the new token as the agent's Machine before starting the runner;
  - `git.spec.ts`, `mockups.spec.ts`, `notifications.spec.ts`, `questions.spec.ts`, and any other spec using `startRunner`: right after minting the runner token, `PATCH /api/agents/{id}` with `runner_token_id`.

- [ ] **Step 1: Edit** the docs and specs.
- [ ] **Step 2: Run** the e2e suite on the `megoo-e2e` stack, as the README describes, with `-f deploy/docker-compose.build.yml`. Expected: all pass.
- [ ] **Step 3: Run** every suite on the branch tip: backend pytest, and frontend vitest, lint and tsc. Expected: all pass.
- [ ] **Step 4: Commit** `docs: one runner token per machine` (with the e2e changes).
