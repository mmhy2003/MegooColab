# Tool Hub MCP servers in runs (MC-31)

Date: 2026-11-16. Branch `megoo/MC-31-every-agent-the-runner-starts-must-see-i`.

Every agent program the runner starts must see the MCP servers the Tool Hub installed for it, keep the run's own `megoocolab` server, and get only the servers marked safe in a read-only run.

## What each agent loads

| Program | Adapter | Where the hub writes its servers | How a run gets them |
|---|---|---|---|
| claude_code | `@agentclientprotocol/claude-agent-acp@0.94.0` (Agent SDK 0.3.303) | `~/.claude.json` `mcpServers` | Passed by the runner in `session/new` / `load` / `resume` (`tools.RunServers`). With `settingSources: []` Claude Code loads no servers from `~/.claude.json` (checked on the SDK's `system/init` message). |
| codex | `@agentclientprotocol/codex-acp@2.3.0` | `$CODEX_HOME/config.toml` `[mcp_servers.<name>]` | Codex loads `config.toml` itself. The runner passes only `megoocolab`; `RunServers` returns nil for codex. |
| omp | `omp acp --approval-mode write` | OMP's `mcp.json` | Passed by the runner (`tools.RunServers`). OMP ignores its own MCP config in ACP mode. |

For claude_code and omp only the hub's own entries go (the manifest's `mcp` entries for that program), never one named `megoocolab`, and a read-only run gets only those marked `ReadOnlySafe`. Hand-made servers are not passed; bring one in with the Tool Hub's import / **Take over**.

## codex-acp 2.3.0 findings

Read from the adapter's source (`src/CodexAcpClient.ts`, `createSessionConfig`), not yet confirmed live:

- Codex loads every `[mcp_servers.*]` table of `config.toml` in every run.
- A server passed in `session/new` whose name `config.toml` already defines is skipped; Codex keeps its own entry. Each skipped server is reported to the client as a failed tool call `mcp__<name>__startup`. Passing hub servers to Codex would therefore add one failed startup line per server and change nothing, so the runner does not.
- There is no clean way to stop Codex loading `config.toml` servers for one run: the adapter's `CODEX_CONFIG` variable loses its `mcp_servers` part as soon as the runner passes `megoocolab`.

## Codex limits

- Non-safe and hand-made `config.toml` servers are loaded in read-only runs too. The runner's read-only policy refuses calls to non-safe tools, so they are visible but not usable. Hiding them needs a per-run `CODEX_HOME` (a strict Codex), which touches Codex's login and session resume and was left out.

## Follow-up

- A developer's own `megoocolab` entry in Codex's `config.toml` wins over the run's: codex-acp skips the run's `megoocolab` (with its run token) and uses the developer's entry. Separate task.

## Live check

Status: **pending**. It was not run for this task: it needs hub pushes and runs started through the server with a runner built from this branch, which could not be done from inside a run. The owner chose to record the steps and run them later.

| Program | OS | Adapter | Workspace | Read-only | Resumed | No duplicate / startup failure |
|---|---|---|---|---|---|---|
| claude_code | | claude-agent-acp 0.94.0 | pending | pending | pending | n/a |
| codex | | codex-acp 2.3.0 | pending | pending | pending | pending |
| omp | | omp (as installed) | pending | pending | pending | n/a |

### How to run it

On a dev machine where the program is installed and logged in:

```
cd runner
go build -o megoocolab-runner .
./megoocolab-runner run    # stop the installed runner first, then connect this build
```

1. In the Tool Hub, push two MCPs to the machine for all three programs: A, http, marked read-only safe; B, stdio, not safe.
2. Workspace run, one task per program, with the prompt "List your MCP servers, then call one tool on each of A and B." Pass: the run log shows both tool calls succeed (`mcp__<server>__<tool>` for Claude Code, `mcp.<server>.<tool>` for Codex).
3. Read-only run with the same prompt. Pass: A's tool works. B is absent (Claude Code, OMP) or its call is refused with a permission line (Codex).
4. Run again on the same task so the session is resumed. Pass: A and B are still there and callable.
5. Codex only: the log has no failed `mcp__<name>__startup` tool call, no server appears twice, and there is exactly one `megoocolab`.

Fill in the table with the date, OS and adapter versions, and add the log lines of any failure.
