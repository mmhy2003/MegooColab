# One runner per machine — design

Date: 2026-10-30. Status: draft for approval.

## Why

The owner works on two computers, Yoga and Legion, each with Claude Code and Codex, so they defined four agents.
They started `megoocolab-runner` on Legion only, and all four agents turned online. They expected only Legion's
two.

Two parts of today's code cause this:

- **The server has no idea of a machine.** On connecting, a runner is sent every agent its user owns (`build_welcome`).
  It checks each one only for "is this program installed here?", so all four pass on Legion.
- **The registry keeps one runner per user** (`RunnerRegistry._conns: user_id → RunnerConn`). Starting the runner
  on Yoga as well would close Legion's (4409 "replaced"), and Yoga would then claim all four agents.

So a person cannot have two machines online at once, and an agent cannot say which machine it lives on.

## The idea (decided by the owner)

**The token defines the person and the machine.**

- A person creates one access token per machine (named, say, "Yoga" and "Legion"). They use it there for both the
  MCP and the runner, as they do today with a single token.
- Each agent is **linked to one token**. A runner connected with a token lights up only that token's agents.
  A token can have several agents, and an agent has at most one token.

## Goals

1. **The link.** Each agent has an optional link to one of its owner's tokens; the user sees it as the agent's
   *machine*. An agent with no link is **unlinked**.
2. **Only the token's agents.** A runner connected with token T is sent, and may report on and run, only the agents
   linked to T. Every other agent of the same user stays offline as far as that runner is concerned.
3. **Several runners per person.** The registry holds one live connection **per token**, not per user. Yoga and
   Legion can be online at the same time. A second runner using the **same** token still replaces the first
   (4409, as today): one token, one machine. *(Claude's call, confirmed by the owner.)*
4. **Unlinked agents stay offline** whatever runner is connected, and show **"Not linked to a machine"** with a
   way to link them (decided by the owner). This includes every existing agent after the update. They are not
   migrated to a guessed token, so the owner links each one once.
5. **Revoking a token unlinks its agents** (decided by the owner: they re-link by hand). Its runner is already
   disconnected by the existing `tokens.revoked` handling. *Claude's call:*
   - The revoke clears the agents' link in the same transaction, so they show as unlinked straight away.
   - The same applies to the bulk revoke (`revoke_user_tokens`) on a password reset and on an admin deactivating a
     user. After a reset, every machine needs a new token and a new `megoocolab-runner login` anyway, so
     re-linking is part of the same chore.
   - The reset-password page's success text and the release note say so.
   - An **expired** token keeps its agents linked but cannot connect. The agent form shows the token as expired, so
     the owner can pick another.
6. **Everything that finds "the agent's runner" uses the agent's token**, not its owner:
   - online/busy/offline status;
   - runner problems;
   - capability checks (workflow, branch);
   - sending runs and queued runs;
   - the A2A and question routing;
   - failing runs when a runner disconnects;
   - the runner ↑ update arrow (`runner_info`).

   A disconnecting Yoga runner fails only runs of Yoga's agents (more exactly: the runs it was given, as today's
   `superseded` logic does), never Legion's.
7. **No runner release.** The server already knows which token a runner connected with (`resolve_bearer` returns
   the user and the token). The protocol, the welcome's shape, and the runner program stay as they are. The welcome
   simply lists fewer agents. This is a MegooColab-only change.

## Non-goals

- A separate "machine" object, or keeping links when a token is replaced. The owner accepts re-linking by hand.
- Restricting what the **MCP** can do per token. An MCP token still acts as its user, as today.
- Auto-linking agents (by hostname, by which program the runner found, or by guessing from a lone token).
- Changing the runner program, its config, or `megoocolab-runner doctor`.

## Anti-goals (a failure even if it works)

- An agent lighting up on a runner whose token it isn't linked to.
- One person's two runners kicking each other off.
- A runner going away and failing, or cancelling, runs that belong to another machine's agents.
- A task dispatched to the wrong machine.
- Existing agents silently attached to some token by the migration.

## How it works

### Data

- `agents.runner_token_id`: nullable FK to `personal_access_tokens.id`, `ON DELETE SET NULL`. Tokens are
  soft-revoked today, so SET NULL is just a safety net. The migration adds the column with every row NULL.
- Linking is allowed only to a token that:
  - belongs to the agent's owner;
  - has the `runner` scope;
  - is neither revoked nor expired at link time.

  Anything else is a 422 with a plain message. Unlinking (null) is always allowed.
- Agent create (`POST /api/agents`) and update (`PATCH /api/agents/{id}`) accept the token id. Agent responses
  give the owner and admins `machine: {token_id, name, expired}` (or null). *Claude's call:* other viewers get no
  machine field; they keep seeing just online/offline.

### Registry and runner socket

- `RunnerRegistry` is keyed by token id. `RunnerConn` carries `token_id` alongside `user_id`.
- `runner_socket` authorizes and keeps the token id; `connect(token_id, user_id, socket)` replaces only a
  connection on the same token.
- `build_welcome` selects the user's agents **with `runner_token_id = <this token>`**. Availability reports for
  agents outside that set are ignored, as reports for unowned agents are today.
- Linking, unlinking or relinking an agent changes the welcome of the affected connections:
  - the old token's runner gets a welcome without the agent, and the new token's runner one with it;
  - availability is recomputed and `agents.updated` published, through the same path that already re-sends
    welcomes when a user's agents or bindings change.
- Lookups that take `owner_id` today (`conn_for_user`, `available_agents`, `supports`) get agent-based
  counterparts that resolve through the agent's token, and every caller listed in goal 6 moves to them. Callers
  that genuinely mean "any runner of this user" (if any remain) must say so explicitly.
- Connection count for the admin "runners connected" figures now counts per token, which is the truthful number.

### Runs when a link changes (Claude's call)

A run belongs to the machine it was sent to. The rules below keep any run from being failed by, or finished on,
the wrong machine.

- **Changing or removing an agent's link while it has a *running* run** is refused (409, "This agent is running
  task X — wait for it to finish or cancel it first"). Queued runs don't block. They simply go to the new machine
  when it is online.
- **Revoking a token** (single or bulk) first closes its runner with 4401. The existing path cancels that
  connection's runs with `runner_unauthorized`. Then the link is cleared.
- **Cleanup keyed to a connection** works per token instead of per user:
  - `fail_disconnected_runs` and `fail_unclaimed_runs` select running runs of agents linked to the connection's
    token (plus, as today, the run ids the connection was given);
  - `finish_run`, `apply_update` and every `run_cancel` sender check, or target, the agent's token connection.

  Because a busy agent cannot be relinked, "the agent's current token" is always the token its running run was
  sent to, so no per-run token column is needed.
- **Upgrade:** after the migration every agent is unlinked, so a run still `running` at deploy time could never be
  reconciled. The migration marks such runs failed with `runner_disconnected`; deploying restarts the backend, which
  already cuts those runs off. A run that the runner still finishes later is ignored, as today for unknown runs.
  Queued runs stay queued and are dispatched once their agent is linked and its machine is online.

### Frontend

- **My agents** (settings → agents):
  - each agent card shows its machine;
  - the Add agent dialog gets a **Machine** select, and the card can change it;
  - the select lists the owner's runner-scope tokens that are neither revoked nor expired, by token name, plus
    "Not linked".
  - An unlinked agent shows **"Not linked to a machine"** with the control to link it.
  - An agent whose token expired shows that, e.g. "Machine token expired — pick another".
  - When the user has no runner-scope token, the select points them to Access tokens.
- *Claude's call:* on the owner's own pages and for admins, the machine name appears next to the agent's status dot
  where there's room (My agents, Admin → Agents). Other surfaces keep just the dot.
- **Access tokens** page: each runner-scope token lists the agents linked to it, and revoking warns how many agents
  will be unlinked.
- **Setup help** (`RunnerSetup`): say "create one token per computer and link each agent to it".
- **Docs:** `docs/install.md` and `runner/README.md` get the same one-token-per-machine guidance.

## Release

This lands on `develop` like any other work. When the owner next says "release", it's a **minor** bump of
MegooColab (a new feature). The release note's **Upgrading** section says that existing agents show "Not linked to
a machine" until each is linked to a token, and how to do it. No runner bump.

## Left to the builder

- Names of the new registry methods, schemas, and the exact `machine` field shape.
- How the per-token welcome refresh is triggered on link changes, reusing today's agents-changed path.
- Test coverage. At least:
  - two tokens of one user both connected, each seeing only its agents;
  - same token twice still replaces;
  - unlinked agents offline;
  - revoke unlinks (single and bulk);
  - relinking a busy agent is refused;
  - the upgrade migration fails leftover running runs;
  - linking validation (other user's token, mcp-only, revoked, expired);
  - a disconnect failing only its own token's runs;
  - dispatch and capability checks per agent;
  - `runner_info` per agent;
  - the frontend select and the "Not linked" state.
