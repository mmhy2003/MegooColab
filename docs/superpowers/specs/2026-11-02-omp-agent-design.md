# OMP agents: a third coding agent program

Status: draft for the owner's approval · 2026-11-02

## Why

MegooColab runs two coding agent programs today: Claude Code and Codex. Some people prefer **OMP** (Oh My Pi,
`@oh-my-pi/pi-coding-agent`, the `omp` command), a terminal coding agent that works with many model providers. The
owner wants MegooColab and its runner to support OMP the same way they support the other two. It is not meant to
bring anything new; it is parity.

Success: someone who uses OMP adds an OMP agent in Settings › My agents, links it to their machine, and it works on
tasks, chats and questions exactly as a Claude Code or Codex agent does, with their Tool Hub tools.

## Goals

- **OMP as a third program** everywhere a program is chosen or named: Add agent, the agent card, chats, questions
  ("prefer an agent program"), task pages, the dashboard, the Tool Hub machine panel and import list, and Admin.
- **Runs**: task workflow runs, chat rounds and answering runs work on OMP with the same read-only and workspace
  rules, steering (messages sent to a running turn), cancel, runs at once, and model/effort choice.
- **Tool Hub**: push installs MCP servers and skills for OMP at user level; **Import from this machine** finds the
  ones set up by hand for OMP; drift is reported like the other programs.
- **MCP setup snippet**: the "Use MegooColab from your own agent" instructions include OMP.
- Windows, Linux and macOS.

## Non-goals

- No OMP-only features (its RPC mode, plan/goal/loop modes, profiles, marketplace, auto-learned skills).
- No installing OMP or signing it in to providers from MegooColab. The person installs `omp` and runs
  `omp auth-broker login` on the machine themselves, as they install and sign in to Claude Code or Codex today.
- No change to how Claude Code or Codex agents behave.

## Anti-goals

- A read-only run (brainstorm, plan, review, answering) must never be able to change the repository on OMP, whatever
  the person's own OMP approval settings say (for example a global "yolo"/auto-approve setting).
- An OMP run must never get MCP servers that a read-only run may not use.
- Supporting OMP must not need the person to edit OMP config by hand.

## What OMP offers (from its docs, v18.x)

- **ACP built in**: `omp acp` serves the Agent Client Protocol over stdio (newline-delimited JSON-RPC). No npx adapter.
- **MCP in ACP mode**: OMP turns its own MCP config off (`enableMCP: false`, "ACP clients own MCP servers"). The only
  MCP servers a run has are the `mcpServers` given in `session/new`.
- **MCP config (user level)**: `~/.omp/agent/mcp.json`, `{"mcpServers": {name: {...}}}`. Entries: `type: "stdio"`
  with `command`, `args`, `env`, `cwd`; or `type: "http"` with `url` (and `headers`). OMP writes to `mcp.json` and
  also reads `.mcp.json` for compatibility. Named profiles move this to `~/.omp/profiles/<name>/agent/`.
- **Skills (user level)**: `~/.omp/agent/skills/<name>/SKILL.md`, one level deep. OMP also discovers skills from
  Claude Code's and Codex/Agents' roots (`~/.claude/skills`, `~/.agents/skills`, ...). A same-named skill from
  another provider stays reachable under a namespaced name unless its body is identical.
- **Permissions**: when an ACP client is connected, `bash`, `edit`, `delete` and `move` ask through
  `session/request_permission` (allow/reject once/always). Approval modes and `--approval-mode`, `--auto-approve`,
  `--yolo` flags exist; settings precedence is flags > `--config` overlay > project config > global config.
- **Model and effort**: `session/new` returns config options; `session/set_config_option` switches the model
  (`provider/id` values) and the thinking level (`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`).
- **Steering**: `_session/steering` (advertised as `_meta.steering.supported`) since **v18.12.6**.
- **Tools**: `--tools <names>` limits the tools a session has (validated against the session's tool names).
- **Install**: `curl -fsSL https://omp.sh/install | sh`, Windows `irm https://omp.sh/install.ps1 | iex`, or
  `bun install -g @oh-my-pi/pi-coding-agent`. Sign-in: `omp auth-broker login [provider]`.

## Decided

### Program

- Program id **`omp`**, label **OMP**. The server's `AgentProgram` gains `omp` (the column is a plain string; no
  migration needed). Every label map (server and web) gets it.
- **Default model for a new OMP agent: none** (OMP's own default, whatever the person set up). Owner's call left to
  the author: OMP works with many providers, so no single model is a sensible default. The model field takes OMP's
  `provider/model` names, and the models and efforts are learned from the agent's first run, as today.

### Runner: starting OMP

- The runner starts `omp acp` directly (the `MEGOO_ADAPTER_OMP` override works like the others).
- Availability: the agent is available when `omp` is found on the PATH and is **v18.12.6 or newer** (the first version
  with steering). Otherwise the agent shows a problem: "omp not found" or "OMP 18.12.6 or newer is needed". Node and
  npx are not required for OMP.
- **Approval**: every OMP run is started with flags that make OMP ask for every gated tool, overriding the person's
  own approval settings, so the runner's existing permission policy decides (as it does for the other programs).
- **Read-only runs** are started with a `--tools` list that drops OMP's file-changing tools (edit, write, delete,
  move, and any code-running tool other than the shell), the way Claude Code's read-only runs drop its edit tools.
  **The shell (`bash`) stays**: the runner's read-only policy lets through only read-only commands
  (`policy.ReadOnlyCommand`: `git log`/`show`/`diff`, `rg`, ...), exactly as for Claude Code; review runs need it to
  read the diff. The permission policy and the repository check after the run stay as the second and third guards.
  *(Author's call, from the builder check: parity with Claude Code.)*
- **If OMP falls short** of what the builder must verify *(author's call)*:
  - if `--tools` would also cut off MCP tools (MegooColab's own included), drop `--tools` and rely on the permission
    policy and the repository check, as Codex runs do;
  - a tool that changes files without asking for permission, or asks without saying which path, is always left out
    with `--tools`, in workspace runs as well as read-only ones;
  - only if no combination keeps read-only runs read-only does the builder stop and bring it back to the owner.
- **The person's own OMP setup is used** *(owner's decision)*: runs see the person's own OMP settings, skills, rules,
  extensions and hooks, as Codex runs see the person's Codex setup (Claude Code's runs, by contrast, are cut off from
  the person's settings). OMP keeps the provider sign-in in the same folder, so this is also what keeps the agent
  signed in. The approval flags still override the person's approval settings, so their own auto-approve never
  reaches a run. Code that the person's own extensions or hooks run is theirs; the repository check after a
  read-only run is the guard against it changing the repository.
- **Profiles** *(author's call)*: if `OMP_PROFILE` (or `PI_PROFILE`) is set in the runner's environment, the runner
  follows it, as OMP does: the Tool Hub installs into `~/.omp/profiles/<name>/agent/`, scans there, and runs (which
  inherit the environment) read from there. Otherwise `~/.omp/agent/`.
- Session mode: none is set (OMP's own modes are not used).

### Runner: MCP servers in OMP runs

Because OMP ignores its own MCP config in ACP mode, the runner hands each OMP run its servers in `session/new`:

- MegooColab's own server, as for every program.
- **Workspace runs**: every hub MCP server installed on this machine for OMP, with its keys.
- **Read-only runs**: only the installed hub servers marked **safe in read-only runs**.

The runner reads these from what it installed for OMP (its manifest and `~/.omp/agent/mcp.json`); a server the person
added to OMP by hand is not passed (the hub only ever touches its own entries).

### Runner: Tool Hub translator for OMP

- **MCP**: entries in `~/.omp/agent/mcp.json` under `mcpServers`, written like the Claude Code translator writes
  `~/.claude.json`: only the hub's own entries change, every other key and entry stays, the file is written atomically
  and privately (keys). HTTP servers become `type: "http"` with `url` and `headers`; command servers become
  `type: "stdio"` with `command`, `args`, `env` (with the same Windows `cmd /c` handling for npx-style launchers).
- **Skills**: `~/.omp/agent/skills/<name>/`.
- **Scan** (import and drift): reads `~/.omp/agent/mcp.json` and `~/.omp/agent/skills`. It does not report skills
  OMP merely discovers in Claude Code's or Codex's folders (those belong to those programs).
- The folder is the active profile's agent folder (see Profiles above), `~/.omp/agent` by default.
- Because OMP also reads Claude Code's and Codex's skill folders, a hub skill pushed to all three programs on one
  machine is the same text in each place, which OMP shows once.

### Server

- Runs to an OMP agent go to a runner that supports it. Runner capability **`omp/1`**: a runner without it never
  receives OMP runs and shows the agent as needing a runner update ("Update the runner to use OMP agents."), the same
  way older runners are handled for other features.
- Hub pushes include `omp` among the programs only for a runner with `omp/1`.

### Web

- Add agent: Program select gains **OMP**. With OMP picked, the Model field starts empty ("Program default").
- MCP setup panel: an **OMP config** snippet for `~/.omp/agent/mcp.json`:
  `{"mcpServers": {"megoocolab": {"type": "http", "url": "<origin>/api/mcp", "headers": {"Authorization": "Bearer <your token>"}}}}`.
- Runner setup help mentions installing OMP and signing in with `omp auth-broker login`.
- Every place that names programs shows "OMP".

### Releases

- A runner release (new minor) and an app release (new minor). Release notes cover installing OMP and the minimum
  version.

## Left to the builder

- The exact `--tools` read-only list and approval flags, taken from OMP's current tool registry and CLI; verify with
  a real `omp acp` that MCP tools stay usable under the list, and that a gated tool asks even with a global
  auto-approve setting.
- Whether OMP's ACP advertises session load/resume, and HTTP MCP; the runner's existing capability probe decides,
  and OMP runs work without load/resume as other adapters do.
- How the fake agent and tests stand in for OMP (the existing `MEGOO_ADAPTER_*` override pattern).
- Version parsing of `omp --version`.

## Testing

- Unit tests for the OMP translator (install, remove, fingerprint, scan, other entries untouched, private write) on
  all three OSes' path rules, the launch command and flags per policy, the MCP servers handed to a run per policy, the
  availability check (missing, too old, fine), and the server's `omp/1` gating.
- An end-to-end test with a real runner and the fake agent standing in for `omp acp`: an OMP agent finishes a task
  run, and a push installs a skill and an MCP server for OMP.
- Before release, a manual check with a real `omp` on the owner's machine: a read-only run cannot edit, a workspace
  run can, a hub MCP server and a hub skill work in a run.
