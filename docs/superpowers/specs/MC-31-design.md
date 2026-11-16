# MC-31: Every agent the runner starts sees its Tool Hub MCP servers

## Goal

A Claude Code run, a Codex run and an OMP run each see the MCP servers the Tool Hub installed for that program, and can call their tools. Each run keeps its own `megoocolab` server, and a read-only run can use only the servers marked safe.

## What I found

| Agent | Today | After this task |
|---|---|---|
| Claude Code | Gets no hub servers (`settingSources: []` also turns off `~/.claude.json`) | The runner passes its hub servers in `session/new` / `load` / `resume` |
| OMP | The runner passes them (`OmpRunServers`) | Same behaviour, through the shared function |
| Codex | Loads `config.toml` by itself (read from source, not yet run live) | Unchanged; proven live and written down |

**Codex, from the source of the pinned `@agentclientprotocol/codex-acp@2.3.0`** (`src/CodexAcpClient.ts`, `createSessionConfig`; not yet run live):

- Codex loads every `[mcp_servers.*]` table of `config.toml` itself, in every run.
- A server passed in `session/new` whose name `config.toml` already defines is **skipped**; Codex uses its own entry. Each skipped server is reported to the client as a failed tool call `mcp__<name>__startup`.
- There is no clean way to stop Codex loading `config.toml` servers for one run. The adapter's `CODEX_CONFIG` variable loses its `mcp_servers` part as soon as the runner passes `megoocolab`.

## Decisions

1. **Codex keeps its own config** (your choice). The runner passes hub servers only to Claude Code and OMP. Passing them to Codex too would add one failed startup line per hub server to every Codex run and change nothing. A strict Codex (a per-run `CODEX_HOME`) was rejected for this task: it touches Codex's login and session resume.
2. **Only hub-installed servers** go to Claude Code and OMP runs (your choice). A hand-made server is brought in with the Tool Hub's import / **Take over**.
3. **A `megoocolab` entry in the developer's own Codex `config.toml` is left out of this task** (your choice). By the adapter's source, the run's own `megoocolab` is then skipped and Codex uses the developer's entry. The finding goes into the note (see Documentation) as a follow-up for a separate task.
4. **Keep Claude Code's `settingSources: []`** and its `allowedTools` as they are. Hub tools stay behind the runner's permission check; only `megoocolab` is pre-approved.
5. **No TOML reader in `RunServers`.** The task proposed one, but with decision 1 nothing would use it.

## Architecture

### `runner/internal/tools`: `RunServers`

Rename `omp_run.go` to `run_servers.go`. `OmpRunServers` becomes:

```go
// RunServers are the hub MCP servers the runner hands a run of program in session/new, load and resume.
func RunServers(m *Manifest, program, home string, readOnly bool) []acp.McpServer
```

- It picks the program's config file:
  - `claude_code`: `claudeJSON(home)` (`~/.claude.json`)
  - `omp`: `ompMCPJSON(home)` (OMP's `mcp.json`)
  - `codex` and any other program: returns nil. A comment says why: Codex loads `config.toml` itself, and codex-acp skips a passed server whose name the config defines.
- The rest is today's `OmpRunServers` body with `e.Program == program`. Both files have the same `mcpServers` shape, read with `readServersAt`. The rules are the same for both programs:
  - only the manifest's `<program>` / `mcp` entries, sorted by name;
  - in a read-only run, only entries with `ReadOnlySafe`;
  - never an entry named `megoocolab`;
  - an entry missing from the file, unreadable, or of another type (not `http`, no `command`) is left out; an unreadable file gives nil;
  - entries go as written in the file (headers, command, args, env), so a Windows `cmd /c` wrap stays.

### `runner/internal/jobs`

- `manager.go` (around line 880): replace the OMP-only branch with one call for every program:
  `servers = append(servers, withSecrets(tools.RunServers(man, agent.Program, home, kind == policy.ReadOnly), rs.Secrets)...)`.
  `WithSafeMcpServers` stays as it is.
- `secrets.go`: `withSecrets` is unchanged; its comment now says it serves every program that gets servers from the runner.
- `session.go` is unchanged: `session/new`, `session/resume` and `session/load` already carry `q.servers`.

### Permissions (no code change)

- Workspace runs: the workspace policy allows MCP tool calls (Claude Code asks with kind `other`).
- Read-only runs: Claude Code and OMP get only safe servers, and `safeMcpCall` allows their tools. For Codex, the non-safe servers are loaded but the read-only policy refuses their calls (kind `execute`, no command).

## Error handling and edge cases

- Manifest or home can't be read: the run starts with only `megoocolab`, as today.
- A hub entry edited by hand is passed as it now stands in the file (today's OMP behaviour). Drift reporting already flags it.
- A hub entry removed by hand from the file is left out.
- A resumed session gets the current list, so a server pushed between two runs reaches the resumed session.
- The names can't clash: `megoocolab` is never passed from the hub, and names in one config file are unique.
- All three programs advertise MCP over http, so no capability check is added for hub http servers.

## Testing

**Unit tests, `runner/internal/tools`** (`run_servers_test.go`):

- The four `OmpRunServers` tests move over as `RunServers(m, "omp", …)` and keep passing.
- A table test for `claude_code` and `omp`. The config file has hub entries `docs` (http, safe, with a header) and `db` (stdio, with env), plus `megoocolab` (also in the manifest) and a hand-made `handmade` (file only):
  - a workspace run gets `[db, docs]` with the header and env;
  - a read-only run gets `[docs]`.
- `codex`: with the same entries in `config.toml` and the manifest, `RunServers` returns none, in both policies.
- An invalid `~/.claude.json` gives none.

**Fake-agent tests, `runner/internal/jobs`** (`omp_test.go` becomes `hub_servers_test.go`):

- `hubServers` writes the fixture for all three programs (`~/.claude.json`, OMP `mcp.json`, Codex `config.toml`, manifest entries).
- One table test over the programs, reading the fake agent's recorded `mcp_servers`:
  - `claude_code` and `omp`: workspace `[db, docs]`, read-only `[docs]`;
  - `codex`: none in both.
- `TestClaudeRunGetsNoHubServers` is replaced by the above.
- A resumed Claude Code run: the `session/resume` (or `session/load`) request carries the hub servers too.
- A workflow run (with `rs.Mcp`) of Claude Code carries exactly one `megoocolab` plus the hub servers.

**Live check on a dev machine**, for each program that is installed and logged in. If one is missing, the builder asks a human to run the written steps.

1. Push two hub MCPs to the machine for all three programs: one http marked safe, one stdio not marked safe.
2. Workspace run with a prompt that asks the agent to list its MCP servers and call one tool on each. Pass: the run log shows both tool calls succeed (`mcp__<server>__<tool>` for Claude Code, `mcp.<server>.<tool>` for Codex).
3. Read-only run with the same prompt. Pass: the safe server's tool works. The other server is absent (Claude Code, OMP) or its call is refused with a permission line (Codex).
4. Run again on the same task so the session is resumed. Pass: the servers are still there.
5. Codex only: the log has no failed `mcp__<name>__startup` line, and no server appears twice.

## Documentation

- New note `docs/superpowers/notes/<date>-hub-servers-in-runs.md`: the live-check steps and results per program, the codex-acp findings above, the known Codex limits, and the `megoocolab`-in-`config.toml` follow-up.
- `docs/superpowers/specs/2026-11-01-tool-hub-design.md`, "Agents must actually see the tools": correct the claim that `~/.claude.json` is read with `settingSources: []`, and say what each agent loads.
- Knowledge Base page **Architecture / Runner (Go)**, "Tool Hub on the machine": the same per-agent facts.

## Out of scope

- Hiding non-safe or hand-made `config.toml` servers from Codex runs (a strict Codex).
- Handling a developer's own `megoocolab` entry in Codex's `config.toml`: separate task.
- Passing hand-made servers to Claude Code or OMP runs.
- Changes to the hub's backend, UI, push or import.
- Changing the pinned adapter versions.