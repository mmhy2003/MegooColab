# OMP Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OMP (Oh My Pi, the `omp` command) becomes a third agent program next to Claude Code and Codex: runs, steering,
models, Tool Hub push/import and every label, on Windows, Linux and macOS.

**Architecture:** The runner starts `omp acp` directly (no npx adapter) with OMP's approval forced to ask, gates its
availability on `omp` ≥ 18.12.6, hands each OMP run its hub MCP servers in `session/new` (OMP ignores its own MCP
config in ACP mode), and gets a Tool Hub translator writing the active OMP agent folder. The runner advertises `omp/1`;
the server sends OMP runs and pushes only to runners with it. The web app adds OMP wherever programs appear.

**Tech Stack:** Go runner (`github.com/coder/acp-go-sdk`), FastAPI + SQLAlchemy backend, Next.js frontend, Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-11-02-omp-agent-design.md`

## Global Constraints

- Program id `omp`, label `OMP` (server `AgentProgram.omp`, runner `adapters.Omp`, web `PROGRAM_LABEL.omp`).
- Minimum OMP version **18.12.6**. Problems, verbatim: `omp not found`, `OMP 18.12.6 or newer is needed`,
  `omp found but cannot be started; reinstall with the OMP installer`.
- Launch: `omp acp --approval-mode always-ask` (every run). `MEGOO_ADAPTER_OMP` replaces the whole command line, as the
  other programs' overrides do, and then no `omp` availability/version check is made.
- Runner capability `omp/1`. Server problem for an OMP agent on a runner without it, verbatim:
  `Update the runner to use OMP agents.`
- **No `--tools` list** (the spec's fallback, decided while planning): OMP validates `--tools` against exact tool
  names, and MCP tools are named `mcp__<server>_<tool>`, unknown before launch, so a list would cut off MegooColab's
  and the hub's MCP tools. Read-only runs rely on the forced approval (`always-ask` prompts for every write and exec),
  the runner's permission policy (read-only commands only), OMP's writes going through the runner's
  `fs/write_text_file` (refused in read-only runs), and the repository check after the run.
- On Windows `exec.LookPath("omp")` finds `omp.exe` or `omp.cmd` through PATHEXT and Go starts either directly (as the
  runner already starts `npx.cmd`); no `cmd /c` is needed for `omp` itself.
- New OMP agent: no default model (`model = None`, the program's own default).
- OMP agent folder: what `omp config path` prints; when `omp` cannot be run, the rule: root = `$PI_CONFIG_DIR` or
  `<home>/.omp`; profile = `$OMP_PROFILE` or `$PI_PROFILE` → `<root>/profiles/<name>/agent`; else
  `$PI_CODING_AGENT_DIR` or `<root>/agent`.
- MCP file `<agent folder>/mcp.json` (`{"mcpServers": {...}}`, entries `type: "http"|"stdio"`), written atomically and
  privately; skills `<agent folder>/skills/<name>/`.
- OMP runs' `session/new` servers: MegooColab's own; workspace runs add every hub MCP installed for `omp`; read-only
  runs add only those marked safe in read-only runs.
- Help copy: macOS/Linux `curl -fsSL https://omp.sh/install | sh`; Windows `irm https://omp.sh/install.ps1 | iex`;
  sign-in `omp auth-broker login`.
- No behaviour change for Claude Code or Codex agents. No Prettier (≈120-column lines). Every commit ends with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A person's own OMP `bash.patterns` "allow" rule runs a changing command in a read-only run without a permission
   card: the repository check after the run must still fail that run (no new code; Task 7 checks it with real omp).
2. `omp acp` asks permission for an edit without `locations`: the workspace policy refuses it ("no path to verify")
   and the agent cannot edit at all. Task 7 checks the shape; if `locations` is empty but `rawInput` carries the
   path, Task 7 adds reading it (test: `TestOmpEditPermissionPathFromRawInput`).
3. OMP's config options do not use the `model` / `thought_level` categories: the agent's chosen model is reported
   unavailable. Task 7 checks; if OMP uses ids `model`/`thinking` without categories, `configSelector` also matches by
   id (test: `TestConfigSelectorMatchesOmpIds`).
4. `mcp.json` holds a person's own entry with the hub tool's name: install refuses to overwrite it (take-over rules,
   as for Claude Code) — pinned in Task 2 by `TestOmpInstallKeepsOtherEntries` and the existing apply tests run per
   translator.
5. A machine with only an `omp.ps1` shim on Windows: the agent shows the "cannot be started" problem rather than
   "not found" — pinned in Task 1 by `TestOmpProblemPowerShellShimOnly`.

---

### Task 1: Runner — start OMP and say when it can't

**Files:**
- Modify: `runner/internal/adapters/adapters.go` (const `Omp`, `forOS` case, package doc)
- Create: `runner/internal/adapters/omp.go`, `runner/internal/adapters/omp_test.go`
- Modify: `runner/internal/adapters/adapters_test.go`
- Modify: `runner/internal/jobs/manager.go` (`probe`: per-program requirements; `Manager.RunVersion` hook)
- Modify: `runner/internal/jobs/manager_test.go`

**Interfaces:**
- Produces: `adapters.Omp = "omp"`; `adapters.OmpMinVersion = "18.12.6"`;
  `adapters.OmpProblem(goos string, getenv func(string) string, lookPath func(string) (string, error), version func(path string) (string, error)) string`
  ("" when fine); `Manager.RunVersion func(path string) (string, error)` (default runs `<path> --version`).

- [ ] **Step 1: Write the failing tests** in `adapters_test.go` / `omp_test.go`:

```go
func TestForOmpStartsAcpWithAskingApprovals(t *testing.T) {
	for _, goos := range []string{"windows", "linux", "darwin"} {
		s, err := forOS(goos, Omp, func(string) string { return "" }, okLook)
		// s.Command == "omp", s.Args == []string{"acp", "--approval-mode", "always-ask"}
	}
}
func TestForOmpOverride(t *testing.T)                 // MEGOO_ADAPTER_OMP=`"C:\fake agent.exe" --x` → Command/Args from it
func TestOmpProblemNotFound(t *testing.T)             // lookPath fails everywhere → "omp not found"
func TestOmpProblemTooOld(t *testing.T)               // version "omp 18.12.5" → "OMP 18.12.6 or newer is needed"
func TestOmpProblemFine(t *testing.T)                 // "18.12.6", "omp v18.13.0 (bun)", "19.0.0" → ""
func TestOmpProblemUnreadableVersion(t *testing.T)    // "" or "dev" → "OMP 18.12.6 or newer is needed"
func TestOmpProblemPowerShellShimOnly(t *testing.T)   // goos windows, lookPath("omp") fails, lookPath("omp.ps1") ok → "omp found but cannot be started; reinstall with the OMP installer"
func TestOmpProblemSkippedWithOverride(t *testing.T)  // MEGOO_ADAPTER_OMP set → "" without calling lookPath
```

and in `manager_test.go`:

```go
func TestProbeOmpNeedsOmpNotNode(t *testing.T)   // LookPath finds only "omp", RunVersion "18.12.6": omp agent available,
                                                 // claude_code agent has "node not found" and "npx not found"
func TestProbeOmpTooOld(t *testing.T)            // omp agent problems == ["OMP 18.12.6 or newer is needed"]
func TestProbeOmpVersionCachedPerPath(t *testing.T) // two probes → RunVersion called once for the same path
```

- [ ] **Step 2: Run them, expect FAIL** — `cd runner && go test ./internal/adapters/ ./internal/jobs/ -run 'Omp'`
  Expected: compile errors (`Omp`, `OmpProblem`, `RunVersion` undefined).

- [ ] **Step 3: Implement.** `forOS` case `Omp` returns `Spec{Program: Omp, Command: "omp", Args: []string{"acp", "--approval-mode", "always-ask"}}`
  (override handled by the shared override code before it). `OmpProblem` parses the first `\d+\.\d+\.\d+` in the
  version output and compares numerically. `probe` builds problems per agent from its program: `claude_code`/`codex`
  keep the node/npx checks, `omp` uses `OmpProblem` (Windows: the `.ps1` check). Cache versions in the Manager by
  resolved path (map under `m.mu`).

- [ ] **Step 4: Run, expect PASS** — `go test ./internal/adapters/ ./internal/jobs/` → `ok`.

- [ ] **Step 5: Commit** — `feat(runner): start OMP agents (omp acp) and report when omp is missing or too old`

---

### Task 2: Runner — Tool Hub translator for OMP

**Files:**
- Create: `runner/internal/tools/omp.go`, `runner/internal/tools/omp_test.go`
- Modify: `runner/internal/tools/claude.go` (`readServers` / `editServers` take the file path and its label, so OMP reuses them)
- Modify: `runner/internal/tools/home.go` (`OmpAgentDir`)

**Interfaces:**
- Consumes: `claudeEntry(*protocol.McpPayload) map[string]any` (same entry shape), `installSkillDir`, `removeSkillDir`,
  `skillFingerprint`, `scanSkills`, `ReplaceFile`, `fingerprintJSON`, `unwrapWindowsCommand`.
- Produces: `func OmpAgentDir(home string) string`; package var `ompConfigPath func() (string, error)` (default runs
  `omp config path`, trimmed; tests replace it); translator `omp{}` registered with `Program() == "omp"`;
  `func ompMCPJSON(home string) string` (= `OmpAgentDir(home)/mcp.json`); `func readServersAt(path, label string) (map[string]json.RawMessage, error)`.

- [ ] **Step 1: Write the failing tests** in `omp_test.go` (each stubs `ompConfigPath` to fail unless it says otherwise):

```go
func TestOmpAgentDirFromOmp(t *testing.T)          // ompConfigPath → "/x/agent" → OmpAgentDir == "/x/agent"
func TestOmpAgentDirRule(t *testing.T) {           // table, env via t.Setenv:
	// none                              → <home>/.omp/agent
	// PI_CONFIG_DIR=/c                  → /c/agent
	// OMP_PROFILE=work                  → <home>/.omp/profiles/work/agent
	// PI_PROFILE=work                   → same
	// PI_CODING_AGENT_DIR=/a            → /a
	// OMP_PROFILE=work + PI_CODING_AGENT_DIR=/a → <home>/.omp/profiles/work/agent (profiles ignore the override)
}
func TestOmpInstallHttpAndStdio(t *testing.T)      // mcp.json mcpServers: {"docs": {"type":"http","url":...,"headers":{...}},
                                                   // "fs": {"type":"stdio","command":...,"args":[...],"env":{...}}}
func TestOmpInstallKeepsOtherEntries(t *testing.T) // a hand-made "mine" entry and a top-level "$schema" key survive install and remove
func TestOmpInstallWindowsWrapsNpx(t *testing.T)   // on windows (skip elsewhere): npx → "cmd", ["/c","npx",...]; scan unwraps it
func TestOmpMCPJSONIsPrivate(t *testing.T)         // owner-only on unix (mode 0600); on windows the existing private helper's test pattern
func TestOmpSkillsInstallScanRemove(t *testing.T)  // <agent>/skills/<name>/SKILL.md; ScanSkills finds it with Program "omp"
func TestOmpScanIgnoresMegooColabAndOtherPrograms(t *testing.T) // "megoocolab" entry not reported; ~/.claude/skills not scanned
func TestOmpFingerprintMatchesInstall(t *testing.T)
```

- [ ] **Step 2: Run, expect FAIL** — `go test ./internal/tools/ -run Omp` → compile errors.

- [ ] **Step 3: Implement** `omp` like `claudeCode`, on `ompMCPJSON(home)` and `OmpAgentDir(home)/skills`, with
  `Program "omp"` in found tools. Generalise `readServers`/`editServers` to a path and a label (error text keeps
  `.claude.json` for Claude Code, says `mcp.json` for OMP). `OmpAgentDir` uses `ompConfigPath` when it succeeds with
  an absolute path, else the rule in Global Constraints.

- [ ] **Step 4: Run, expect PASS** — `go test ./internal/tools/` → `ok` (the existing apply/drift/scan tests now also
  see the `omp` translator through `Programs()`; fix any test that hard-codes two programs to name its programs).

- [ ] **Step 5: Commit** — `feat(runner): Tool Hub installs MCP servers and skills for OMP`

---

### Task 3: Runner — OMP runs get their hub MCP servers; omp/1; doctor

**Files:**
- Modify: `runner/internal/tools/plugin.go` (or new `runner/internal/tools/omp_run.go`): `OmpRunServers`
- Modify: `runner/internal/jobs/manager.go` (append OMP servers to the session's servers)
- Modify: `runner/internal/protocol/protocol.go` (`CapabilityOmp`, hello list), `runner/internal/conn/conn_test.go`
- Modify: `runner/cmd/doctor.go`, `runner/cmd/doctor_test.go`
- Tests: `runner/internal/tools/omp_test.go`, `runner/internal/jobs/manager_test.go`

**Interfaces:**
- Consumes: `Manifest.Entries`, `readServersAt`, `ompMCPJSON`, `jobs.mcpServers`.
- Produces: `func OmpRunServers(m *Manifest, home string, readOnly bool) []acp.McpServer`;
  `protocol.CapabilityOmp = "omp/1"`.

- [ ] **Step 1: Write the failing tests**

```go
func TestOmpRunServersWorkspaceHasAll(t *testing.T)   // manifest omp mcp "docs"(safe), "db"(not safe); mcp.json holds both + "mine"
                                                      // → servers named docs and db (http → McpServerHttpInline with headers;
                                                      // stdio → McpServerStdio with command/args/env), never "mine"
func TestOmpRunServersReadOnlyOnlySafe(t *testing.T)  // readOnly → only "docs"
func TestOmpRunServersSkipsMissingOrUnreadable(t *testing.T) // manifest names an entry no longer in mcp.json → left out, no error
func TestOmpRunGetsHubServers(t *testing.T)           // jobs: an omp run's session/new McpServers = megoocolab + the hub's (fake agent records them)
func TestClaudeRunGetsNoHubServers(t *testing.T)      // jobs: unchanged for claude_code
```

  `conn_test` capability list gains `"omp/1"`. `doctor_test`:

```go
func TestDoctorOmpMissingIsNotAFailure(t *testing.T) // line "omp: ok — not found; needed only for OMP agents …", report returns nil when everything else is ok
func TestDoctorOmpTooOld(t *testing.T)               // the omp line says "OMP 18.12.6 or newer is needed" and doctor fails
func TestDoctorAcpSkipsOmpWhenNotInstalled(t *testing.T) // reportACP prints "omp: not installed" and does not fail for it
```

- [ ] **Step 2: Run, expect FAIL** — `go test ./internal/tools/ ./internal/jobs/ ./internal/conn/ ./cmd/`.

- [ ] **Step 3: Implement.** In the run, after `mcpServers(rs.Mcp)`, when `agent.Program == adapters.Omp` and the
  manifest loads, append `tools.OmpRunServers(man, home, kind == policy.ReadOnly)`. `doctor`: an `omp` check line using
  `adapters.OmpProblem` (missing → OK with the hint naming the install command for the OS and `omp auth-broker login`;
  too old / cannot start → not OK); `acpPrograms` gains `adapters.Omp`, skipped as "not installed" when `OmpProblem`
  says not found.

- [ ] **Step 4: Run, expect PASS** — `go test ./... && go vet ./...` → all `ok`.

- [ ] **Step 5: Commit** — `feat(runner): OMP runs get their hub MCP servers; advertise omp/1; doctor checks omp`

---

### Task 4: Server — OMP program, capability gating, problems, hub programs

**Files:**
- Modify: `backend/app/agents/models.py` (`AgentProgram.omp`), `backend/app/agents/service.py` (`PROGRAM_LABELS`,
  `DEFAULT_MODELS[omp] = None`, `agent_problems(..., program=...)`), `backend/app/agents/router.py` (create: a `None`
  default model), `backend/app/runner/registry.py` (`OMP_CAPABILITY = "omp/1"`, `OMP_PROBLEM`),
  `backend/app/agent_runs/service.py` (`_claim_next`), `backend/app/hub/machines.py` (`machine_programs`)
- Test: `backend/tests/agents/test_omp_agents.py`

**Interfaces:**
- Produces: `AgentProgram.omp = "omp"`; `registry.OMP_CAPABILITY`; `registry.OMP_PROBLEM = "Update the runner to use OMP agents."`;
  `agent_problems(agent_id, owner_id, viewer, chooses=False, program: str | None = None)`.

- [ ] **Step 1: Write the failing tests** (patterns: `tests/agent_runs/test_runs_at_once.py` `_fake_conn`,
  `tests/agents/test_agents.py`, hub tests in `tests/hub/`):

```python
async def test_omp_agent_defaults(client, db):
    # POST /api/agents {"program": "omp"} → 201, name "<Name>'s OMP", model None
async def test_omp_run_waits_for_a_runner_with_omp(client, db):
    # fake conn without "omp/1": queued run stays queued, agent problems include "Update the runner to use OMP agents."
    # add "omp/1" and dispatch: run_start sent
async def test_claude_agent_unaffected_by_omp_capability(client, db):
    # claude_code agent on a conn without "omp/1": run starts, no OMP problem
async def test_hub_push_programs_include_omp_only_with_capability(client, db):
    # machine with an omp and a claude_code agent: machine_programs == ["claude_code"] without omp/1,
    # ["claude_code", "omp"] with it
async def test_question_prefers_omp_program(client, db):
    # POST a question with prefer_program "omp" → 201 and preference echoed
```

- [ ] **Step 2: Run, expect FAIL** — `cd backend && uv run pytest tests/agents/test_omp_agents.py -q` → 422 on `"omp"`.

- [ ] **Step 3: Implement.** `_claim_next`: `omp_ok = agent.program != AgentProgram.omp or registry.agent_supports(agent.id, OMP_CAPABILITY)`
  joins `model_ok`. `agent_problems` appends `OMP_PROBLEM` for `program == "omp"` on a conn without the capability;
  every caller passes the agent's program. `machine_programs` drops `omp` when the token's live conn lacks
  `OMP_CAPABILITY` (no conn: keep it, the push waits for the runner and is built again on delivery).

- [ ] **Step 4: Run, expect PASS** — the new file, then the whole suite once:
  `uv run pytest -q > <workspace>/pytest.txt 2>&1` → all passed (never two pytest runs at once; dev DB).

- [ ] **Step 5: Commit** — `feat(agents): OMP agent program on the server, sent only to runners with omp/1`

---

### Task 5: Web — OMP everywhere a program shows

**Files:**
- Modify: `frontend/src/lib/agents.ts` (`PROGRAM_LABEL.omp = "OMP"`, `DEFAULT_MODEL.omp = ""`),
  `frontend/src/lib/questions.ts` (`PROGRAM_NAME` → `PROGRAM_LABEL`), `frontend/src/components/questions/AskQuestion.tsx`
  (`PROGRAMS` from `PROGRAM_LABEL`), `frontend/src/components/chats/ChatView.tsx` (`PROGRAM_LABEL[c.agent.program]`),
  `frontend/src/app/(app)/settings/agents/page.tsx` (Program option), `frontend/src/components/agents/McpSetup.tsx`,
  `frontend/src/components/agents/RunnerSetup.tsx`, `frontend/src/lib/api-types.ts` (`npm run gen:api`)
- Tests: `frontend/src/app/(app)/settings/agents/__tests__/add.test.tsx`, `frontend/src/components/agents/__tests__/McpSetup.test.tsx`,
  `RunnerSetup.test.tsx`, an AskQuestion/ChatView test where one exists

- [ ] **Step 1: Write the failing tests**

```tsx
it("an OMP agent starts on the program's own default model", ...)
  // pick Program "OMP" → Model field "" ; POST body { program: "omp", model: null }
it("shows the OMP config for ~/.omp/agent/mcp.json", ...)
  // McpSetup: label "OMP config", value contains '"megoocolab"', '"type": "http"', `${origin}/api/mcp`,
  // '"Authorization": "Bearer <your token>"'; note mentions ~/.omp/agent/mcp.json
it("tells OMP users how to install and sign in", ...)
  // RunnerSetup Set up tab: Windows shows "irm https://omp.sh/install.ps1 | iex", Linux / macOS shows
  // "curl -fsSL https://omp.sh/install | sh", both show "omp auth-broker login"
it("names OMP agents in a chat and as a question preference", ...)
```

- [ ] **Step 2: Run, expect FAIL** — `npx vitest run <those files>`.

- [ ] **Step 3: Implement.** OMP snippet value, verbatim shape:
  `{"mcpServers": {"megoocolab": {"type": "http", "url": "<origin>/api/mcp", "headers": {"Authorization": "Bearer <your token>"}}}}`
  pretty-printed, with the note "Add this to `~/.omp/agent/mcp.json` (merge it into `mcpServers` if the file exists)."
  RunnerSetup: under Set up, an "OMP agents only" line with the platform's install command and
  `omp auth-broker login`.

- [ ] **Step 4: Run, expect PASS** — `npx vitest run && npx tsc --noEmit -p . && npx eslint <changed files>`.

- [ ] **Step 5: Commit** — `feat(web): OMP as an agent program, with its MCP config and setup help`

---

### Task 6: CI on macOS and an OMP end-to-end test

**Files:**
- Modify: `.github/workflows/ci.yml` (runner matrix `os: [ubuntu-latest, windows-latest, macos-latest]`)
- Modify: `frontend/e2e/helpers/runner.ts` (`MEGOO_ADAPTER_OMP` = the fake agent, next to Claude Code's)
- Create: `frontend/e2e/omp.spec.ts`

- [ ] **Step 1: Write the e2e test** `an OMP agent finishes a task and gets its hub tools` (pattern:
  `e2e/parallel.spec.ts` for setup/cleanup, `e2e/hub.spec.ts` for the push): project `OMP`, agent
  `{program: "omp", name: "OMP e2e agent"}`, runner with the fake agent as `omp`; the card shows "Online"; a chat on the
  agent reaches its first agent message (`say("Hello from OMP")`); a pushed skill lands in
  `<home>/.omp/agent/skills/<name>/SKILL.md` and a pushed HTTP MCP in `<home>/.omp/agent/mcp.json`, and the panel shows
  "OMP: installed". Cleanup deletes the project, the agent and its token, as `parallel.spec.ts` does.

- [ ] **Step 2: Run the full e2e suite** on the `megoo-e2e` stack (scratchpad `e2e-run-*.sh` pattern; never the
  owner's `megoocolab-*` containers). Expected: all passed, the new one included.

- [ ] **Step 3: Commit** — `test(e2e): OMP agent on a real runner; ci: runner tests on macOS`

---

### Task 7: Check against a real `omp` (owner's go-ahead)

Installing OMP touches the machine outside the repository: **ask the owner first**. With their go-ahead, install
OMP (Windows: `irm https://omp.sh/install.ps1 | iex`), have them sign in (`omp auth-broker login`; never read or
handle their credentials), then with the runner built from the branch:

- [ ] `megoocolab-runner doctor` and `doctor --acp`: omp line ok; the omp ACP line lists its capabilities.
- [ ] `omp config path` equals `tools.OmpAgentDir` (print both from a tiny `go test -run` helper or the doctor output).
- [ ] A read-only run (brainstorm) on a scratch repo: an attempted edit is refused, a `git diff` runs, `submit_design`
  works; with a global `tools.approvalMode: yolo` in the person's OMP settings the edit is still refused.
- [ ] A workspace run edits a file inside the worktree. If OMP's edit permission has no `locations`, add reading the
  path from `rawInput` in `acpclient` with `TestOmpEditPermissionPathFromRawInput` (Review Focus 2).
- [ ] The chosen model and effort apply. If OMP's config options lack the categories, add id matching in
  `configSelector` with `TestConfigSelectorMatchesOmpIds` (Review Focus 3).
- [ ] A hub skill and a hub MCP server pushed to the machine work in a run.
- [ ] *(final review)* `omp acp` really ignores `mcp.json`: push a hub MCP **not** marked safe, start a read-only run,
  and confirm its tools are absent. If present, start OMP with its own MCP config off and test it.
- [ ] *(final review)* With `--approval-mode always-ask`, does OMP ask before MCP tool calls? If so, note the title
  shape and make `acpclient` recognise MegooColab's own tools and safe hub servers in it (exact server prefix, no
  command), with tests, so `submit_design` / `submit_answer` / `ask_human` work in read-only runs.
- [ ] *(final review)* Compare OMP's settings before and after a first run, with and without a chosen model, and
  time that first run: if the model/effort sweep changes the person's own OMP default or takes long, skip the sweep
  for `omp` and learn levels only for the model in use, with a test.
- [ ] Ledger every finding as a ruling; commit any fix with its test (`fix(runner): …`).

If the owner declines, ledger it, and list these checks in the final message as still to do before release.
