# Tool Hub, part 2: pushing to your machines — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With one push, a person's Tool Hub tools are installed at user level on their own machines, for every agent
program they run there, on Windows, Linux and macOS. Machines that don't match the library are flagged. Tools already
set up by hand can be imported, and agents actually get to use the tools.

**Architecture:** This builds on plan 23 (the library).
- **The server** keeps, per machine (a runner token):
  - the ticked tools;
  - the last report per tool and program;
  - a pending flag.
- **A push** sends the machine's **whole wanted set** (`tools_push`). The runner reconciles its manifest against it:
  it installs or updates what is wanted, removes what it installed and is no longer wanted, and never touches entries
  it didn't install.
- **The runner side** is a new `internal/tools` package:
  - neutral types;
  - one translator per program (Claude Code and Codex);
  - the manifest;
  - atomic private file writes;
  - the drift check and the import scan.
- **Agents see the tools in two ways:**
  - user-level MCP entries reach Claude Code sessions as they are (`~/.claude.json` is read regardless of
    `settingSources`);
  - hub skills reach Claude Code sessions through a runner-built local plugin.

  `Safe in read-only runs` MCPs are allowed by the ACP client in read-only runs.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, pytest; Go (runner), `github.com/pelletier/go-toml/v2` (new, for
reading Codex config); Next.js, TanStack Query, Vitest; Playwright.

**Spec:** `docs/superpowers/specs/2026-11-01-tool-hub-design.md`. Plan 23 is
`docs/superpowers/plans/2026-11-01-plan-23-tool-hub-library.md`.

## Global Constraints

- **Branch:** `feat/plan-24-tool-hub-push`, cut from `develop` after plan 23 is merged.
- **Capability string:** `tools/1`.
- **Messages:**
  - Server to runner: `tools_push` and `tools_scan`.
  - Runner to server: `tools_report`, `tools_drift` and `tools_found`.
  - Each is mirrored exactly in `backend/app/runner/protocol.py` and `runner/internal/protocol/protocol.go`, and gets an
    entry in `protocol_test.go`'s key-set test.
- **Programs:** `claude_code` and `codex` (the existing `AgentProgram` values). A push installs only into the programs
  of the agents linked to that machine.
- **Operating systems:** the runner's `runtime.GOOS` `windows`, `linux` and `darwin` map to the hub's `windows`,
  `linux` and `macos`. The server resolves `os_commands` for the machine's OS before sending.
- **Where tools go:**

  | Program | MCP servers | Skills |
  |---|---|---|
  | Claude Code | `<home>/.claude.json`, top-level key `mcpServers.<name>` | `<home>/.claude/skills/<name>/` |
  | Codex | `<CODEX_HOME or home/.codex>/config.toml`, table `[mcp_servers.<name>]` | `<home>/.agents/skills/<name>/` (Codex's current user skills root; `~/.codex/skills` is deprecated) |

  In the table, `<home>` is `os.UserHomeDir()`.
- **The Claude Code MCP entry shape:**
  - `{"type":"http","url":…,"headers":{…}}` for http;
  - `{"type":"stdio","command":…,"args":[…],"env":{…}}` for stdio.
- **The Codex MCP entry shape:**
  - for http, `url` plus an `http_headers` table;
  - for stdio, `command`, `args` and an `env` table.
- **The Windows command fix:** when the OS is Windows and `command` is one of `npx npm pnpm pnpx yarn bunx` (with or
  without `.cmd`), write `command: "cmd"`, `args: ["/c", <command>, ...args]`.
- **The runner manifest** is `os.UserConfigDir()/megoocolab/tools-manifest.json`. Entries are `{program, kind, name,
  tool_id, rev, fingerprint, read_only_safe}`. The runner never edits or removes an entry that isn't in its manifest.
- **Files holding secrets** (`.claude.json`, Codex `config.toml`, the manifest) are private:
  - on Linux and macOS, mode `0600`;
  - on Windows, a DACL granting only the current user, set through `golang.org/x/sys/windows`.

  They are written atomically: write a temp file in the same folder, make it private, then rename it. If the target's
  size or mtime changed between the read and the rename, the runner re-reads and retries, up to 3 times.
- **Runner tests never touch the real home:** every Go test that reaches `internal/tools` sets `HOME`, `USERPROFILE`,
  `APPDATA`, `XDG_CONFIG_HOME` and `CODEX_HOME` (to `""`) to `t.TempDir()` paths with `t.Setenv`. The e2e runner
  already runs with `isolatedEnv(home)`.
- **Secrets:**
  - The only decrypting path is `build_push(db, token_id)` in the backend. Its output goes only to
    `conn.send(...)` for a connection whose `user_id` owns the token.
  - `tools_report` and `tools_drift` carry no values.
  - `tools_found` (import) does carry values. The server keeps it only Fernet-encrypted (`hub_scans.result_enc`) and
    deletes it after accept, or after 1 hour.
  - The scan API returns values that look like secrets masked as `••••` plus their last 4 characters.
- **Machine states, exact copy:**

  | State | Shown as |
  |---|---|
  | `installed` | installed |
  | `update_ready` | update ready |
  | `will_install` | will install |
  | `will_remove` | will remove |
  | `changed` | changed on this machine |
  | `conflict` | made by hand on this machine |
  | `key_missing` | key missing: can't install yet |
  | `removed` | push to uninstall |
  | `failed` | failed: {detail} |
  | `not_supported` | not supported by {Program} |
  | `not_available` | not available on {OS} |
  | `waiting` | waiting for the machine to come online |

- **Panel copy:**
  - the buttons are `Push {n} change(s)`, `Import from this machine` and `Take over`;
  - the default-set switch reads `When I add an agent on a new machine, install my default set there`;
  - the tool-page checkbox reads `In my default set`;
  - a machine whose runner lacks `tools/1` shows `Update the runner to use the Tool Hub.`
- **Error codes,** added to `MESSAGES`:

  | Code | Message |
  |---|---|
  | `hub_key_missing` | Some tools still need their keys. |
  | `hub_not_your_machine` | That machine isn't yours. |
  | `hub_runner_offline` | The machine is offline. Try again when it's online. |
  | `hub_runner_too_old` | Update the runner to use the Tool Hub. |
  | `hub_scan_expired` | That import has expired. Run it again. |

- The plan 23 constraints on migrations, tests, tooling and commit trailers apply unchanged. The runner tests run with
  `cd runner && go test -count=1 ./... && go vet ./...`.

## Review Focus

1. **A user's `~/.claude.json` with other content** (projects, history, OAuth and many unrelated keys): after a push,
   every unrelated key is still there with the same value. Only `mcpServers.<ours>` changed. Test in Task 3.
2. **A Codex `config.toml` with comments, unrelated tables and a hand-made `[mcp_servers.other]`:** the push changes
   only our table and its subtables, byte for byte everywhere else. Test in Task 4.
3. **A runner offline during a push, whose library changes before it reconnects:** on reconnect it receives the
   library as it is at delivery time, and the panel goes from `waiting` to the real states. Test in Task 7.
4. **A hand-made MCP entry with the same name as a hub tool:** the push leaves it alone and reports `conflict`. Only
   `Take over` overwrites it, and after that it's managed. Tests in Tasks 5 and 7.
5. **A tool deleted from the library while installed on machines:** it shows `will_remove`, and the next push removes
   it from every program on that machine. Test in Task 7.

---

### Task 1: Protocol messages and the machine's OS

**Files:**
- Modify: `backend/app/runner/protocol.py`, `backend/app/runner/router.py` (Hello stores the OS),
  `backend/app/auth/models.py` (`PersonalAccessToken.runner_os: String(10) | None`)
- Modify: `runner/internal/protocol/protocol.go`, `runner/internal/protocol/protocol_test.go`
- Create: the migration `<rev>_runner_os.py` (only the new token column; Task 7 has its own migration)
- Test: `backend/tests/runner/test_protocol.py` (extend), `runner/internal/protocol/protocol_test.go`

**Interfaces:**
- Produces (both languages, field names exact):
  - `McpPayload{transport: "http"|"stdio", url?, headers: {str:str}, command?, args: [str], env: {str:str}}`, with
    secrets and placeholders already filled in.
  - `SkillFile{path, content_b64}`.
  - `ToolPayload{tool_id, name, kind, rev, read_only_safe, mcp?: McpPayload, files?: [SkillFile]}`.
  - `ToolsPush{type:"tools_push", push_id, programs: [str], tools: [ToolPayload], take_over: [str]}`, where
    `take_over` lists tool names.
  - `ToolsScan{type:"tools_scan", scan_id}`.
  - `ToolResult{tool_id?, name, kind, program, rev?, status: "installed"|"removed"|"failed"|"conflict"|"not_supported"|"not_available", detail}`.
  - `ToolsReport{type:"tools_report", push_id, results: [ToolResult]}`.
  - `ToolDrift{name, kind, program, status: "changed"|"missing"}`.
  - `ToolsDrift{type:"tools_drift", items: [ToolDrift]}`.
  - `FoundTool{program, kind, name, mcp?: McpPayload, files?: [SkillFile], problem?}`.
  - `ToolsFound{type:"tools_found", scan_id, items: [FoundTool]}`.
  - Go constructors `NewToolsReport`, `NewToolsDrift` and `NewToolsFound` turn nil lists into empty ones.
    `CapabilityTools = "tools/1"` is added to `NewHello`.
- The backend Hello handler stores `runner_os` on the token row, normalized as `darwin` → `macos`; any other value is
  stored as-is, truncated to 10 characters.
- Limits (backend validation):
  - `tools` at most 200;
  - each skill's decoded files at most 2 MiB;
  - `items` at most 500;
  - a `problem` or `detail` at most 300 characters, NUL-stripped like the other runner text.

- [ ] **Step 1: Write the failing tests:**
  - Go: key-set entries for the five messages, a round-trip for `ToolsPush` with one MCP and one skill, and `NewHello`
    containing `tools/1`.
  - Python: `runner_message` parses `tools_report`, `tools_drift` and `tools_found`, and refuses unknown fields. A
    Hello with `os="darwin"` sets the token's `runner_os == "macos"`.
- [ ] **Step 2: Run** `cd runner && go test ./internal/protocol/` and
  `cd backend && uv run pytest tests/runner -q`. Expected: FAIL.
- [ ] **Step 3: Implement** both mirrors and the OS column, then generate the migration against `megoo_migrate`.
- [ ] **Step 4: Run** the same commands, plus `uv run pytest tests/core/test_migrations.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(runner,hub): tool push protocol and the machine's OS`.

### Task 2: Runner: home, private atomic writes, manifest

**Files:**
- Create: `runner/internal/tools/doc.go`, `types.go`, `home.go`, `files.go`, `private_windows.go`, `private_other.go`,
  `manifest.go`
- Test: `runner/internal/tools/files_test.go`, `manifest_test.go`, `testenv_test.go` (helper `isolate(t) (home string)`
  that sets the env vars from Global Constraints)

**Interfaces:**
- Produces:
  - `type Tool = protocol.ToolPayload` (decoded skill files are kept as `[]File{Path string; Content []byte}` by
    `DecodeFiles(p protocol.ToolPayload) ([]File, error)`)
  - `func Home() (string, error)`, which is `os.UserHomeDir()`
  - `func CodexHome(home string) string`, which is `$CODEX_HOME` if set, else `home/.codex`
  - `func WriteFileAtomic(path string, data []byte, private bool) error`
  - `func ReplaceFile(path string, edit func(old []byte) ([]byte, error), private bool) error`, the read-edit-write
    with the 3-try retry on concurrent change; a missing file is `old == nil`
  - `func MakePrivate(path string) error`
  - `type Entry struct{Program, Kind, Name, ToolID string; Rev int; Fingerprint string; ReadOnlySafe bool}`
  - `type Manifest struct{Entries []Entry}`
  - `func LoadManifest() (*Manifest, error)`: a missing file gives an empty manifest
  - `func (m *Manifest) Save() error`, which writes privately
  - `func (m *Manifest) Find(program, kind, name string) *Entry`
  - `Put(e Entry)` and `Remove(program, kind, name string)`

- [ ] **Step 1: Write the failing tests:**
  - `TestWriteFileAtomicPrivate`: after the write, on non-Windows `Mode().Perm() == 0o600`. On Windows, skip the mode
    check, assert `MakePrivate` returns nil, and assert the file is readable.
  - `TestReplaceFileRetriesOnConcurrentChange`: an `edit` func that modifies the file on disk the first time it's
    called gives a result that contains both changes, and `edit` was called twice.
  - `TestManifestRoundTrip`, and `TestManifestPathUnderConfigDir` (the path starts with the isolated
    `APPDATA`/`XDG_CONFIG_HOME`).
- [ ] **Step 2: Run** `go test ./internal/tools/`. Expected: FAIL.
- [ ] **Step 3: Implement** the files listed above. Add `golang.org/x/sys/windows` usage in `private_windows.go` (the
  module is already a dependency).
- [ ] **Step 4: Run** `go test ./internal/tools/ && GOOS=windows go vet ./internal/tools/`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(runner): private atomic writes and the tools manifest`.

### Task 3: Runner: Claude Code translator

**Files:**
- Create: `runner/internal/tools/translator.go`, `runner/internal/tools/claude.go`
- Test: `runner/internal/tools/claude_test.go`

**Interfaces:**
- Produces:
  - `type Translator interface`, with methods:
    - `Program() string`
    - `InstallMCP(home string, t Tool) (fingerprint string, err error)`
    - `RemoveMCP(home, name string) error`
    - `MCPFingerprint(home, name string) (fp string, exists bool, err error)`
    - `InstallSkill(home string, name string, files []File) (string, error)`
    - `RemoveSkill(home, name string) error`
    - `SkillFingerprint(home, name string) (string, bool, error)`
    - `ScanMCP(home string) ([]protocol.FoundTool, error)`
    - `ScanSkills(home string) ([]protocol.FoundTool, error)`
  - `func For(program string) (Translator, bool)`: a registry holding `claude_code` and `codex`
  - `func WindowsCommand(goos, command string, args []string) (string, []string)`: the Windows command fix
  - `func fingerprintJSON(v any) string` (sha256 hex of canonical JSON) and `func fingerprintFiles([]File) string`
    (sha256 over sorted `path\x00content`)
- `.claude.json` is decoded as `map[string]json.RawMessage` so unrelated keys are kept as raw bytes, and written back
  with two-space indentation. Only the `mcpServers` member is decoded further, as `map[string]json.RawMessage`. The
  fingerprint covers only our entry's JSON.
- Skills are written into a temp folder next to the target, then renamed over it. The old folder is removed only after
  that rename succeeds.
- Scanning reads `mcpServers` (types `stdio`, `http` and a missing type with `command`; anything else gives a
  `problem` "not supported: <type>") and `~/.claude/skills/*/` (≤ 2 MiB each, else `problem` "too large"). The name
  `megoocolab` is skipped.

- [ ] **Step 1: Write the failing tests:**
  - `TestClaudeInstallKeepsOtherKeys`: start from `{"projects":{"x":{"a":1}},"oauthAccount":{"k":"v"},"mcpServers":{"mine":{"type":"stdio","command":"foo"}}}`.
    Install an http tool `ctx` with header `X-Key: s3cret`. Then `projects`, `oauthAccount` and `mcpServers.mine` are
    deep-equal to before, and `mcpServers.ctx` is `{"type":"http","url":…,"headers":{"X-Key":"s3cret"}}`.
  - `TestClaudeRemoveOnlyOurs`.
  - `TestClaudeFingerprintChangesOnHandEdit`.
  - `TestWindowsCommand`: `("windows","npx",["-y","p"])` gives `("cmd",["/c","npx","-y","p"])`.
    `("linux","npx",…)` is unchanged, and so is `("windows","node",…)`.
  - `TestClaudeSkillInstallReplace`: installing v1 with `a.md`, then v2 without it, leaves no `a.md`.
  - `TestClaudeScan`: finds `mine` as stdio and a skill folder, and skips `megoocolab`.
- [ ] **Step 2: Run** `go test ./internal/tools/ -run Claude`. Expected: FAIL.
- [ ] **Step 3: Implement** the translator interface and the Claude Code translator as listed above.
- [ ] **Step 4: Run** `go test ./internal/tools/`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(runner): Claude Code translator for MCP servers and skills`.

### Task 4: Runner: Codex translator

**Files:**
- Create: `runner/internal/tools/codex.go`, `runner/internal/tools/tomlblock.go`
- Modify: `runner/go.mod` (add `github.com/pelletier/go-toml/v2`, used for reading only)
- Test: `runner/internal/tools/codex_test.go`, `runner/internal/tools/tomlblock_test.go`

**Interfaces:**
- Produces:
  - `func replaceTable(doc []byte, name string, block []byte) []byte`: removes the line `[mcp_servers.<name>]` and every
    following line up to the next table header that isn't `[mcp_servers.<name>.…]`. With a non-nil `block`, it appends
    `block` at the end, separated by one blank line. Every other byte is untouched.
  - `func renderCodexBlock(name string, mcp protocol.McpPayload) []byte`: TOML basic strings with escaping.
    - http: `url = "…"`, then `[mcp_servers.<name>.http_headers]`.
    - stdio: `command`, `args = [ … ]`, then `[mcp_servers.<name>.env]`.

    Names with characters outside `[A-Za-z0-9_-]` are quoted (`[mcp_servers."a.b"]`).
  - A Codex `Translator`: `config.toml` under `CodexHome(home)`; skills under `home/.agents/skills/<name>`; the
    fingerprint is the sha256 of the parsed table re-marshalled as canonical JSON. `ScanMCP` parses with go-toml, and
    `ScanSkills` reads both `home/.agents/skills` and the deprecated `CodexHome/skills`.

- [ ] **Step 1: Write the failing tests:**
  - `TestReplaceTableKeepsEverythingElse`: the input has a comment header, `model = "x"`, a hand-made
    `[mcp_servers.other]`, our `[mcp_servers.ctx]` with a `[mcp_servers.ctx.http_headers]` subtable, and a trailing
    `[profiles.a]`. Replacing `ctx` changes only that region, and the rest is byte-for-byte equal (compare prefix and
    suffix).
  - `TestRenderEscapes`: a header value with `"` and `\` parses back with go-toml to the same string.
  - `TestCodexInstallFreshFile`: no file before; afterwards it parses, has the table, and is private.
  - `TestCodexScan`: finds `other` (stdio) and a skill under `.agents/skills`.
- [ ] **Step 2: Run** `go test ./internal/tools/ -run 'Codex|Table|Render'`. Expected: FAIL.
- [ ] **Step 3: Implement** the Codex translator and the TOML helpers as listed above.
- [ ] **Step 4: Run** `go test ./internal/tools/`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(runner): Codex translator, editing only our tables`.

### Task 5: Runner: apply a push, drift, scan, and wiring into the manager

**Files:**
- Create: `runner/internal/tools/apply.go`, `runner/internal/tools/drift.go`, `runner/internal/tools/scan.go`
- Modify: `runner/internal/jobs/manager.go` (Dispatch cases `tools_push` and `tools_scan`; send `tools_drift` once
  after each welcome), `runner/internal/protocol/protocol.go` (`NewHello` capability, already done in Task 1)
- Test: `runner/internal/tools/apply_test.go`, `runner/internal/jobs/tools_test.go` (uses `newEnvWithCache` plus
  `isolate`)

**Interfaces:**
- Produces:
  - `func Apply(home string, m *Manifest, programs []string, tools []Tool, takeOver []string) []protocol.ToolResult`.
    For each program in `programs`:
    1. For each tool, look up the translator. If there is none, the result is `not_supported`.
    2. If the program's target already holds an entry with that name that is **not** in the manifest, and the tool
       isn't in `takeOver`, the result is `conflict`.
    3. Otherwise, install the tool, put its manifest entry with the new fingerprint and `rev`, and report
       `installed`. A failure gives `failed` with the error text, which must never contain values.
    4. Finally, every manifest entry for this program whose name isn't among `tools` is removed from disk and from the
       manifest, and reported `removed`.

    The manifest is saved once, at the end.
  - `func Drift(home string, m *Manifest) []protocol.ToolDrift`: for each manifest entry, a fingerprint mismatch gives
    `changed`, and a missing entry gives `missing`.
  - `func Scan(home string, m *Manifest) []protocol.FoundTool`: covers every registered translator. Entries present in
    the manifest are excluded.
  - In the manager:
    - `tools_push` runs `Apply` off the message loop, in one goroutine at a time (a mutex), then sends `tools_report`.
    - `tools_scan` runs `Scan`, then sends `tools_found`.
    - After handling each `welcome`, the manager sends `tools_drift`.

- [ ] **Step 1: Write the failing tests:**
  - `TestApplyConflictThenTakeOver`.
  - `TestApplyRemovesUnwanted`.
  - `TestApplyOnlyListedPrograms`: `programs=["claude_code"]` leaves no `config.toml` created.
  - `TestDriftAfterHandEdit`.
  - `TestScanExcludesManaged`.
  - jobs: the test server sends `tools_push` with one http tool. The runner replies `tools_report` with `installed`, and
    `<home>/.claude.json` holds the entry. After a reconnect and welcome, a `tools_drift` frame arrives with no items.
    Hand-editing the file and reconnecting gives `changed`.
- [ ] **Step 2: Run** `go test ./internal/tools/ ./internal/jobs/ -run 'Apply|Drift|Scan|Tools'`. Expected: FAIL.
- [ ] **Step 3: Implement** `Apply`, `Drift` and `Scan`, and the manager wiring, as listed above.
- [ ] **Step 4: Run** `go test -count=1 ./... && go vet ./...`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(runner): apply pushes, report drift, scan for import`.

### Task 6: Runner: agents get the tools (skills plugin, read-only allowance)

**Files:**
- Create: `runner/internal/tools/plugin.go`
- Modify: `runner/internal/adapters/adapters.go` (`SessionMeta` gains a `plugins` argument),
  `runner/internal/acpclient/client.go` (option `WithSafeMcpServers(names []string)`), `runner/internal/jobs/manager.go`
  (passes both per run, from the manifest)
- Test: `runner/internal/tools/plugin_test.go`, `runner/internal/adapters/adapters_test.go`,
  `runner/internal/acpclient/client_test.go`

**Interfaces:**
- Produces:
  - `func SyncPlugin(cacheRoot, home string, m *Manifest) (dir string, err error)`: builds `<cacheRoot>/hub-plugin/`
    with `.claude-plugin/plugin.json` `{"name":"megoocolab-hub","description":"Skills from your MegooColab Tool Hub"}`
    and `skills/<name>/` copied from `home/.claude/skills/<name>` for each Claude Code skill in the manifest. It returns
    `""` when there are none. It runs after every `Apply` and at startup.
  - `func SessionMeta(program string, p policy.Kind, pluginDir string) map[string]any`: for Claude Code with a
    non-empty `pluginDir`, it adds `"plugins": []map[string]any{{"type":"local","path": pluginDir}}`. All existing keys
    are unchanged; `settingSources` stays `[]`.
  - `acpclient.WithSafeMcpServers(names)`: in `RequestPermission`, a tool whose title is `mcp__<name>__<tool>` (Claude
    Code) or `mcp.<name>.<tool>` with `_meta.is_mcp_tool_approval` (Codex), for a listed name, is allowed with the
    reason "Tool Hub MCP marked safe in read-only runs". This mirrors `megooColabMcpCall`. Unlisted MCP tools keep
    today's policy decision.
  - The manager collects the safe names from manifest entries with `ReadOnlySafe` for the run's program.

- [ ] **Step 1: Write the failing tests:**
  - `TestSyncPluginCopiesOnlyManagedClaudeSkills` (a hand-made skill isn't copied).
  - `TestSessionMetaPlugins`, with and without a plugin dir.
  - `TestSafeMcpAllowedInReadOnly`: read-only policy, title `mcp__ctx__resolve`, kind other. Listed: allow. Unlisted:
    deny. The Codex title form also passes.
- [ ] **Step 2: Run** `go test ./internal/tools/ ./internal/adapters/ ./internal/acpclient/`. Expected: FAIL.
- [ ] **Step 3: Implement** the plugin sync, the `SessionMeta` change and the ACP client option as listed above.
- [ ] **Step 4: Run** `go test -count=1 ./... && go vet ./...`. Expected: PASS.
- [ ] **Step 5: Manual check, recorded in the ledger.** On a dev machine with the real adapters, push a test skill and
  start a Claude Code run, then confirm the skill is listed. If it isn't, record a `Ruling:` with what the adapter
  needs. Run the same check for Codex: confirm a pushed MCP server and an `~/.agents/skills` skill are visible through
  `codex-acp`.
- [ ] **Step 6: Commit** `feat(runner): agents get hub skills and read-only-safe MCPs`.

### Task 7: Backend: machines, wants, push, reports, drift

**Files:**
- Modify: `backend/app/hub/models.py`, adding:
  - `HubMachine(token_id PK, FK personal_access_tokens CASCADE; pending: bool = False; requested_at, delivered_at, reported_at: DateTime | None)`
  - `HubMachineWant(token_id, tool_id; PK both; FKs CASCADE)`
  - `HubInstall(IdMixin; token_id FK CASCADE; tool_id FK SET NULL; name; kind; program; rev: int | None; status: str; detail: Text = ""; updated_at)`,
    unique `hub_installs_token_id_name_kind_program_key`
  - `HubTool.in_default_set: bool = False`
  - `HubPrefs(user_id PK FK CASCADE; auto_default: bool = False)`
- Create: `backend/app/hub/machines.py` (service), `backend/app/hub/machines_router.py`, the migration
  `<rev>_hub_machines.py`
- Modify: `backend/app/runner/router.py` (route the three runner messages; on a Hello with `tools/1`, deliver if
  pending), `backend/app/agents/router.py` (default-set trigger on create, and on PATCH of `runner_token_id`)
- Test: `backend/tests/hub/test_machines.py`, `backend/tests/runner/test_tools_messages.py`

**Interfaces:**
- Produces (service):
  - `machine_programs(db, token_id) -> list[str]`: distinct programs of the agents linked to the machine
  - `build_push(db, token_id) -> ToolsPush`. It contains:
    - the wanted tools that aren't removed and have no missing secrets;
    - each MCP resolved for `runner_os`, with secrets and placeholders filled in, and `os_commands[os]` used over
      `command`;
    - a tool with no command for that OS left out, and recorded as `not_available`.
  - `deliver(db, token_id) -> bool`: if a connection owned by the token's user has `tools/1`, it sends `build_push`,
    sets `delivered_at`, and clears `pending`
  - `apply_report(db, token_id, ToolsReport)`, `apply_drift(db, token_id, ToolsDrift)`
  - `machine_states(db, user) -> list[MachineOut]`
- Produces (routes, prefix `/api/hub/machines`, `AuthedUser`, only the user's own runner tokens, else 404
  `hub_not_your_machine`):
  - `GET ""` returns `list[MachineOut]`. `MachineOut` has:
    - `{token_id, name, os, online, supports_tools, agents: [{id,name,program}], pending, reported_at}`
    - `tools: [{tool_id, name, kind, ticked, programs: [{program, state, detail}]}]`
    - `out_of_step: bool`
  - `GET /summary` returns `{out_of_step: bool}`.
  - `POST /{token_id}/push` with body `{tool_ids: [UUID], take_over: [UUID]}`:
    - it replaces the wants;
    - it is 409 `hub_key_missing` (with no partial change) if any ticked tool has missing secrets;
    - it is 409 `hub_removed` if any ticked tool is removed;
    - it sets `pending`, calls `deliver`, and returns the `MachineOut`.
  - `PUT /api/hub/prefs` with `{auto_default: bool}`, and `PATCH /api/hub/tools/{id}` accepting `in_default_set`
    (owner only, also on copies).
- States per (machine, tool, program) follow Global Constraints and are computed from wants, installs, `tool.rev` and
  the pending flag. A machine is `out_of_step` when any state is other than `installed`, or when it's `pending`.
- The default-set trigger: when an agent is created or linked to a machine that has no `HubMachine` row, and the
  owner's `auto_default` is on, the wants become the default set (tools without missing secrets), and the server sets
  `pending` and delivers.

- [ ] **Step 1: Write the failing tests:**
  - `test_push_delivers_resolved_secrets`: use a fake `RunnerConn` registered in the registry with `tools/1` (follow
    the existing runner tests' fakes). The pushed payload has the header value filled in and `${API_KEY}` replaced in
    the URL. The HTTP response doesn't contain the value.
  - `test_push_offline_waits_then_delivers_current_state`: push while offline, so the state is `waiting`. Change the
    tool, then connect a Hello with `tools/1`. The delivered payload has the new `rev`.
  - `test_report_marks_installed_then_update_ready_after_edit`.
  - `test_deleted_tool_will_remove`.
  - `test_conflict_then_take_over`: a report with `conflict` gives state `conflict`. A push with `take_over` includes
    the name in `take_over`.
  - `test_programs_from_linked_agents`: linking a Codex agent to a machine whose Claude Code entries are installed
    gives `will_install` for `codex`.
  - `test_drift_changed`.
  - `test_key_missing_409`, `test_not_your_machine_404`, `test_runner_too_old_supports_tools_false`.
  - `test_default_set_on_new_machine`.
  - `test_windows_os_command`: a machine with `runner_os="windows"` and `os_commands.windows` set gets the windows
    command. A machine with `runner_os="linux"`, no default command and only a windows entry gets `not_available`.
- [ ] **Step 2: Run** `uv run pytest tests/hub/test_machines.py tests/runner/test_tools_messages.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the models, migration, service, routes and runner routing as listed above.
- [ ] **Step 4: Run** `uv run pytest -q` (the whole suite) and ruff. Expected: PASS.
- [ ] **Step 5: Commit** `feat(hub): push tools to your machines and track what they report`.

### Task 8: Backend: import

**Files:**
- Modify: `backend/app/hub/models.py` (`HubScan(IdMixin; token_id FK CASCADE; user_id FK CASCADE; status: "waiting"|"done"; result_enc: Text | None; created_at)`),
  `backend/app/hub/machines.py`, `backend/app/hub/machines_router.py`, `backend/app/runner/router.py`
- Test: `backend/tests/hub/test_import.py`

**Interfaces:**
- Produces (routes):
  - `POST /api/hub/machines/{token_id}/scan` returns 202 `{scan_id}`. It is 409 `hub_runner_offline` or
    `hub_runner_too_old`.
  - `GET /api/hub/scans/{id}` (owner only) returns `{status, items: [ImportItem]}`, or 410 `hub_scan_expired` after 1
    hour. Each `ImportItem` is:
    - `{index, kind, name, programs: [str], problem?}`;
    - for an MCP, `mcp: {transport, url, command, args, headers/env: [{name, value_masked, suggested_secret}]}`;
    - for a skill, `files: [{path, size}]`;
    - `exists_in_library: bool`.

    Identical MCPs found in several programs merge into one item (`programs` lists them all). Merging compares the
    canonical JSON of the payload.
  - `POST /api/hub/scans/{id}/accept` with `{items: [{index, name, secret: [str], description}]}` returns
    `list[ToolOut]`. It creates the tools: values of entries named in `secret` go to the secrets store, the rest to the
    spec. Placeholders aren't introduced automatically. Afterwards the scan row is deleted.
- `tools_found` from the runner fills `result_enc`.

- [ ] **Step 1: Write the failing tests:** the merge across programs; masking (`ghp_abcdefghijklmnopqrstu1234` is
  shown as `••••1234` and suggested secret); accepting stores the secret encrypted and the plain value doesn't appear in
  `resp.text`; a skill is imported with its files; expiry; another user's scan is 404.
- [ ] **Step 2: Run** `uv run pytest tests/hub/test_import.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the model, routes and runner routing as listed above.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(hub): import tools already set up on a machine`.

### Task 9: Frontend: the machine panel, push, import, default set, the dot

**Files:**
- Create: `frontend/src/components/hub/MachineTools.tsx`, `frontend/src/components/hub/ImportDialog.tsx`
- Modify: `frontend/src/app/(app)/settings/agents/page.tsx` (renders one `MachineTools` per machine above the agent
  list), `frontend/src/lib/hub.ts` (keys and hooks `useHubMachines`, `useHubSummary`),
  `frontend/src/components/shell/Sidebar.tsx` (a dot on `Tool Hub` when `out_of_step`),
  `frontend/src/app/(app)/hub/[id]/page.tsx` (the `In my default set` checkbox), `frontend/src/lib/errors.ts`
- Test: `frontend/src/components/hub/__tests__/MachineTools.test.tsx`,
  `frontend/src/components/hub/__tests__/ImportDialog.test.tsx`, `frontend/src/components/shell/__tests__/Sidebar.test.tsx`
  (extend)

**Interfaces:**
- `MachineTools({machine})`:
  - the title `Tools on "<name>"`, the OS, and `Agents here: <name> (<Program>)…`;
  - one row per library tool (except removed ones that aren't installed), each with a checkbox, a kind Badge and one
    state chip per program, using the copy from Global Constraints;
  - `conflict` rows show a `Take over` button, which adds the tool to `take_over` for the next push;
  - `Push {n} change(s)`, enabled when the ticks differ from the saved wants or any state is out of step. When any
    ticked tool is `changed`, it asks first with `useConfirm` (warn): "This puts your library's version back over the
    hand edits on this machine.";
  - `Import from this machine` opens `ImportDialog`;
  - the default-set switch, with its copy;
  - a runner without `tools/1` shows only the update copy.
- `ImportDialog({tokenId})`:
  - it POSTs the scan, then polls `GET /api/hub/scans/{id}` every 1.5 s until `done` (60 s timeout, then the message
    "The machine didn't answer. Try again.");
  - it lists the items with a checkbox, an editable name and a per-value `Secret` checkbox, pre-ticked from
    `suggested_secret`;
  - items that `exists_in_library` are unticked, with the note `Already in your library`;
  - `Add {n} to my library` accepts.
- The Sidebar dot: a span with `aria-label="Tool Hub needs a push"` next to the label, using `useHubSummary` (refetch
  every 60 s).

- [ ] **Step 1: Write the failing tests:**
  - MachineTools:
    - the chips render the exact copy for each state;
    - ticking and pushing POSTs `{tool_ids, take_over:[]}`;
    - the `Take over` button adds that tool to `take_over`;
    - a `changed` tool triggers the confirm;
    - a too-old runner shows the update copy.
  - ImportDialog: a masked value shows as given, a suggested secret is pre-ticked, and accept POSTs the chosen
    `secret` names.
  - Sidebar: with `out_of_step: true`, the dot is present.
- [ ] **Step 2: Run** `npx vitest run src/components/hub src/components/shell`. Expected: FAIL.
- [ ] **Step 3: Implement** the components and page changes as listed above (after `npm run gen:api`).
- [ ] **Step 4: Run** `npx vitest run src`, then eslint and tsc. Expected: PASS and clean.
- [ ] **Step 5: Commit** `feat(hub): push panel per machine, import, default set`.

### Task 10: End to end

**Files:**
- Modify: `frontend/e2e/hub.spec.ts` (adds a test)

- [ ] **Step 1: Write** `tool hub: push to a machine and see it installed`:
  1. Mint a linked runner token for a fake Claude Code agent, then start the runner with `isolatedEnv(home)` (existing
     helpers).
  2. Add an http MCP with a secret header, set the secret, open My agents, tick it, and press `Push 1 change`.
  3. Expect `installed`.
  4. Read `<home>/.claude.json` from the test: it has `mcpServers.<name>.headers.X-Key` equal to the secret.
  5. Edit the file by hand, restart the runner, and expect `changed on this machine`.
  6. Push again (confirm), then expect `installed`.
- [ ] **Step 2: Run** with the `megoo-e2e` stack: this spec, then the full suite, then `down -v`. Expected: all pass.
- [ ] **Step 3: Commit** `test(e2e): push a Tool Hub MCP to a machine`.
