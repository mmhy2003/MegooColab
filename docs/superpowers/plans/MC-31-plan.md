# MC-31 plan: every agent the runner starts sees its Tool Hub MCP servers

**Goal.** Claude Code and OMP runs get their hub-installed MCP servers in `session/new` / `load` / `resume`; Codex keeps loading its own `config.toml` (unchanged, proven live); read-only runs get only safe servers; no run gets a second `megoocolab`.

**Architecture.** `tools.OmpRunServers` becomes `tools.RunServers(m, program, home, readOnly)` in a renamed file `run_servers.go`. It reads `~/.claude.json` for `claude_code`, OMP's `mcp.json` for `omp`, and returns nil for `codex` and anything else. `jobs/manager.go` calls it for every program instead of the OMP-only branch. Docs (new note, Tool Hub design, KB Runner page) record what each agent loads and the live check.

## File map

| File | Change |
|---|---|
| `runner/internal/tools/omp_run.go` → `runner/internal/tools/run_servers.go` | `git mv`; `OmpRunServers` → `RunServers(m *Manifest, program, home string, readOnly bool) []acp.McpServer`; `sortedKeys` moves with it |
| `runner/internal/tools/omp_test.go` | remove `runServersSetup`, `serverNames` and the four `TestOmpRunServers*` tests (moved) |
| `runner/internal/tools/run_servers_test.go` (new) | moved tests + per-program table test + codex + invalid `.claude.json` |
| `runner/internal/jobs/manager.go` (~line 880) | one `RunServers` call for every program |
| `runner/internal/jobs/secrets.go` | `withSecrets` comment only |
| `runner/internal/jobs/omp_test.go` → `runner/internal/jobs/hub_servers_test.go` | `git mv`; fixture for all three programs; table test; resume; workflow run |
| `runner/internal/jobs/manager_test.go` | `newEnvWithCache` also sets `MEGOO_ADAPTER_CODEX` to the fake agent |
| `docs/superpowers/notes/2026-11-16-hub-servers-in-runs.md` (new) | live-check steps and results, codex-acp findings, Codex limits, `megoocolab`-in-`config.toml` follow-up |
| `docs/superpowers/specs/2026-11-01-tool-hub-design.md` | fix "Agents must actually see the tools" |
| KB page **Architecture / Runner (Go)** | "Tool Hub on the machine": per-agent facts |

## Steps

### 1. tools: replace OmpRunServers with RunServers for claude_code and omp

`git mv runner/internal/tools/omp_run.go runner/internal/tools/run_servers.go`, then write the new function:

```go
// RunServers are the hub MCP servers the runner hands a run of program in session/new, load and resume. Claude Code
// runs start with settingSources: [], which also leaves ~/.claude.json's servers out, and OMP turns its own MCP
// config off in ACP mode, so the runner hands both their hub servers. Codex gets none: codex-acp loads every
// [mcp_servers.*] table of config.toml itself, and skips a passed server whose name the config already defines.
// Only the hub's own entries (the manifest's) go, as written in the program's file; a read-only run gets only
// those marked safe; never one named "megoocolab". An entry missing, unreadable or of another type is left out.
func RunServers(m *Manifest, program, home string, readOnly bool) []acp.McpServer {
	var path, label string
	switch program {
	case "claude_code":
		path, label = claudeJSON(home), ".claude.json"
	case "omp":
		path, label = ompMCPJSON(home), "mcp.json"
	default:
		return nil
	}
	servers, err := readServersAt(path, label)
	if err != nil {
		return nil
	}
	var names []string
	for _, e := range m.Entries {
		// the run's own server, with its run token, is the only "megoocolab"
		if e.Program == program && e.Kind == "mcp" && e.Name != megooColabServer && (e.ReadOnlySafe || !readOnly) {
			names = append(names, e.Name)
		}
	}
	// ... the rest exactly as today's OmpRunServers body (sort, unmarshal, http / stdio cases)
}
```

Tests (`runner/internal/tools/run_servers_test.go`, package `tools`): move `runServersSetup`, `serverNames` and the four tests out of `omp_test.go`, renamed `TestRunServersOmpWorkspaceHasAll`, `TestRunServersOmpReadOnlyOnlySafe`, `TestRunServersOmpNeverPassesMegooColab`, `TestRunServersOmpSkipsMissingOrUnreadable`, calling `RunServers(m, "omp", home, …)`. Add:

```go
// hubFixture writes the same config for program: hub entries docs (http, safe, header) and db (stdio, env),
// megoocolab (also in the manifest) and handmade (file only).
const hubMCPServers = `{"mcpServers":{
	"docs":{"type":"http","url":"https://d/mcp","headers":{"X-Key":"k"}},
	"db":{"type":"stdio","command":"node","args":["db.js"],"env":{"PW":"p"}},
	"megoocolab":{"type":"http","url":"https://elsewhere"},
	"handmade":{"type":"http","url":"https://h"}}}`

func hubManifest(program string) *Manifest {
	return &Manifest{Entries: []Entry{
		{Program: program, Kind: "mcp", Name: "docs", ReadOnlySafe: true},
		{Program: program, Kind: "mcp", Name: "db"},
		{Program: program, Kind: "mcp", Name: "megoocolab", ReadOnlySafe: true},
	}}
}
```

- `TestRunServersPerProgram`: table over `claude_code` (write `hubMCPServers` to `filepath.Join(home, ".claude.json")`) and `omp` (`writeOmpJSON`). Workspace: names `[db, docs]`, `db` Stdio `Command "node"`, `Args ["db.js"]`, `Env [{PW p}]`; `docs` Http `Url "https://d/mcp"`, `Headers [{X-Key k}]`. Read-only: `[docs]`.
- `TestRunServersCodexGetsNone`: write `config.toml` at `codexConfig(home)` (mkdir its dir) with `[mcp_servers.docs]` `url = "https://d/mcp"` and `[mcp_servers.db]` `command = "node"`; manifest `hubManifest("codex")`; `RunServers(m, "codex", home, false)` and `(…, true)` both have length 0.
- `TestRunServersInvalidClaudeJSON`: `.claude.json` = `{broken`; `RunServers(hubManifest("claude_code"), "claude_code", home, false)` is empty.

In the same step, `jobs/manager.go` keeps compiling: change the call to `tools.RunServers(man, adapters.Omp, home, kind == policy.ReadOnly)` keeping the OMP-only condition (step 2 widens it).

Run: `cd runner; go test ./internal/tools/ -run RunServers` first fails (undefined: RunServers), after the change passes; then `go build ./... ; go vet ./internal/tools/ ./internal/jobs/ ; go test ./internal/tools/ ./internal/jobs/`.

Commit: `feat(runner): RunServers reads hub MCP servers for claude_code and omp (MC-31)`

### 2. jobs: hand every program its hub servers; fake-agent tests

Test first. `git mv runner/internal/jobs/omp_test.go runner/internal/jobs/hub_servers_test.go`. In `manager_test.go` `newEnvWithCache`, add `t.Setenv("MEGOO_ADAPTER_CODEX", `"`+testutil.BuildFakeAgent(t)+`"`)` next to the OMP line.

Rewrite `hubServers(t, home)` to write the fixture for all three programs:
- `~/.claude.json` and `~/.omp/agent/mcp.json` with `{"mcpServers":{"docs":{"type":"http","url":"https://d/mcp"},"db":{"type":"stdio","command":"node","args":["db.js"]},"megoocolab":{"type":"http","url":"https://elsewhere"},"handmade":{"type":"http","url":"https://m"}}}`;
- `filepath.Join(tools.CodexHome(home), "config.toml")` with `[mcp_servers.docs]\nurl = "https://d/mcp"\n\n[mcp_servers.db]\ncommand = "node"\nargs = ["db.js"]\n`;
- manifest: for each of `claude_code`, `codex`, `omp`: `docs` (mcp, safe), `db` (mcp), `megoocolab` (mcp, safe).

Tests (replace `TestOmpRunGetsHubServers` and `TestClaudeRunGetsNoHubServers`):
- `TestRunGetsHubServers`: table over program × policy: `claude_code` and `omp` → workspace `[db, docs]`, read_only `[docs]`; `codex` → `[]` both. Each case: `isolateHome`, `hubServers`, `newEnvWithCache(t, "[]", 1, t.TempDir())`, `e.welcomeAs(1, program)`, `e.startRun(...)`, outcome `completed`, compare `sessionServers(t, e)` (it returns `[]string{}` for none).
- `TestResumedClaudeRunGetsHubServers`: subtests `session/load` and `session/resume` like `TestResumedSessionGetsMetaAndModeLikeANewOne` in `resume_test.go` (set `FAKEAGENT_SESSIONS_DIR`, and `FAKEAGENT_RESUME=1` for resume; scenario `twoTurns`). Second run resumes `*first.SessionID`; assert `finalReport().SessionEvents[0]` starts with `load:` / `resume:` and `sessionServers` = `[db, docs]`.
- `TestWorkflowClaudeRunHasOneMegooColab`: `ep := newMcpEndpoint(t)`; `e.startRunWith("r1", "MEG-1", withMcp(ep.URL+"/api/mcp"))`; `sessionServers` = `[db, docs, megoocolab]`, and the `megoocolab` entry's url is `ep.URL+"/api/mcp"` (unmarshal `finalReport().McpServers` with `name`/`url`).

Run `cd runner; go test ./internal/jobs/ -run 'HubServers|RunGetsHubServers|ResumedClaudeRunGetsHubServers|WorkflowClaudeRunHasOneMegooColab'`: claude_code cases fail (no hub servers).

Implement in `manager.go`:
```go
	if man, err := tools.LoadManifest(); err == nil {
		opts = append(opts, acpclient.WithSafeMcpServers(tools.SafeServers(man, agent.Program)))
		// Claude Code (settingSources: []) and OMP (ACP mode) load no MCP config of their own: their hub servers come
		// with the session. Codex loads config.toml itself, so RunServers gives it none.
		if home, err := tools.Home(); err == nil {
			servers = append(servers, withSecrets(tools.RunServers(man, agent.Program, home, kind == policy.ReadOnly), rs.Secrets)...)
		}
	}
```
`secrets.go`: comment becomes "withSecrets adds the run's secrets to the environment of each stdio MCP server the runner hands a run (Claude Code and OMP start them with exactly that environment)."

Run the same command (passes), then `go vet ./internal/jobs/ ; go test ./internal/...`.

Commit: `feat(runner): pass hub MCP servers to Claude Code runs too (MC-31)`

### 3. Live check on a dev machine and the note

Build the runner (`cd runner; go build ./cmd/...` per the README), connect it, and for each program installed and logged in on the machine follow the design's live check: push one http MCP marked safe and one stdio not safe to all three programs; workspace run asking to list MCP servers and call one tool on each; read-only run; a re-run on the same task (resumed session); Codex: no `mcp__<name>__startup` failure and no duplicate. If a program can't be run here, call `ask_human` with the written steps and wait for the results.

Write `docs/superpowers/notes/2026-11-16-hub-servers-in-runs.md`: what each agent loads (table), the steps above, results per program with date/OS/adapter version, the codex-acp 2.3.0 findings (loads all `config.toml` servers; skips a passed server whose name the config defines and reports `mcp__<name>__startup`; `CODEX_CONFIG` loses `mcp_servers` once `megoocolab` is passed), the Codex limits (non-safe and hand-made `config.toml` servers are loaded in read-only runs; the policy refuses non-safe calls), and the follow-up: a developer's own `megoocolab` in `config.toml` wins over the run's.

Commit: `docs: MC-31 live check of hub MCP servers in runs`

### 4. Tool Hub design and KB Runner page

In `docs/superpowers/specs/2026-11-01-tool-hub-design.md`, "Agents must actually see the tools" (line ~216): replace the "MCP servers" bullet: with `settingSources: []` Claude Code loads no servers from `~/.claude.json` (tested with claude-agent-acp 0.94.0), so the runner passes Claude Code's and OMP's hub servers in `session/new` / `load` / `resume` (`tools.RunServers`); replace the "Codex" bullet with: codex-acp loads `config.toml` servers itself, the runner passes none; link the note. Also fix the line ~47 mention if it repeats the claim.

KB: `kb_search("Runner (Go)")`, `kb_read` the page, then `kb_write` the "Tool Hub on the machine" section: Claude: hub servers passed in each session (`settingSources: []` loads none from `~/.claude.json`); Codex: loads `config.toml` itself, runner passes none; OMP: unchanged. Keep the rest of the page.

Commit: `docs: what each agent loads from the Tool Hub (MC-31)`

## Final verification

```
cd runner
go build ./...
go vet ./...
go test ./internal/tools/ ./internal/jobs/ ./internal/fakeagent/
go test ./...
```
Plus the live-check results recorded in the note for Claude Code, Codex and OMP.
