# MegooColab runner

`megoocolab-runner` runs your coding agents (Claude Code, Codex) on your own machine
and connects them to a MegooColab server. The server queues work; the runner starts
the agent in a git worktree and reports progress back.

## Requirements

- Node.js 20 or newer with `npx` on the PATH (the agent adapters are started through it).
- `git`.
- A MegooColab personal access token with the **runner** scope (Profile, Tokens).

## Install

Linux and macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh
# system-wide instead of ~/.local/bin:  ... | sh -s -- --system
# pin a version:                        MEGOO_RUNNER_VERSION=1.2.3 sh install.sh
```

The script downloads the archive for your OS and CPU from the latest `runner-v*`
GitHub release and verifies it against `checksums.txt`.

Windows (Scoop):

```powershell
scoop install https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/scoop/megoocolab-runner.json
```

The release workflow points the manifest at each new `runner-v*` release (version, URLs
and SHA-256 hashes), so this command always installs the latest runner, and
`scoop update megoocolab-runner` updates it.

Manual: download the archive for your platform from the
[releases page](https://github.com/mmhy2003/MegooColab/releases) (tags `runner-v*`),
check it against `checksums.txt`, and put `megoocolab-runner` on your PATH.

## Use

```sh
megoocolab-runner login --url https://megoo.example.com --token mgc_...
megoocolab-runner doctor     # checks config, server, Node.js, git and the agent adapters
megoocolab-runner run        # connect and wait for work (Ctrl+C to stop)
```

`login` writes `runner.json` (URL and token, mode 0600) to your user config directory.
Use one token per computer: an agent runs only on the runner signed in with the token it is linked to (My agents →
Machine). Each computer's runner can be online at the same time; a second runner signing in with the same token
replaces the first.

### Run in the background

```sh
megoocolab-runner service install   # checks the login, registers and starts it; no admin rights needed
megoocolab-runner service status
megoocolab-runner service stop
megoocolab-runner service start
megoocolab-runner service uninstall
```

The service runs as you, because the adapters need your agent logins and repositories.
`service install` refuses until `login` has been done, then registers the runner, starts it and
prints `service status`. `service start` does nothing when the runner is already running.
Re-running `service install` replaces the installation.

- **Linux:** a systemd user unit, enabled for `default.target`, so it starts when your user
  manager does. Run `loginctl enable-linger $USER` once to keep it running when you are
  logged out. When the server ends the session for good (the token was revoked, or another
  runner signed in with the same token) the runner exits with status 78 and systemd does not
  restart it: run `login` again, then `service start`. A missing or unusable `runner.json`
  also exits 78, with no restart. `service install` also replaces a unit in the `failed` state.
- **macOS:** a LaunchAgent in `~/Library/LaunchAgents`, loaded at login, that launchd restarts
  after a crash. After exit 78 (token revoked or replaced, or not logged in) the runner exits 0
  under launchd and stays down: run `login`, then `service start`. A plain `kill` also leaves it
  down until `service start` or the next login. **Existing installs:** run `service install`
  once after updating to get this behaviour.
- **Windows:** an `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` entry starts
  `megoocolab-runner run --background` at sign-in. It starts a hidden supervisor (a brief
  console flash is possible) and exits. The supervisor starts the runner and restarts it after a
  crash: after 5 s, doubling up to 2 min, and back to 5 s after 5 min of uptime. It stops
  restarting after a clean stop or exit 78. Task Manager therefore shows two
  `megoocolab-runner.exe` processes. `service stop` stops both (a stop request, then the process
  tree is ended after 15 s). `service status` shows `running (pid N)` (the supervisor), `stopped`
  or `not installed`, the stored `autostart:` command line, and a warning when that file no
  longer exists or the entry is disabled in Task Manager → Startup apps. `service install`
  re-enables a disabled entry.
  **The runner starts only after you sign in; a machine waiting at the sign-in screen (for
  example after Windows Update) has no runner.**

No admin rights are needed on any OS. On Linux and macOS, `service install` captures your
current `PATH` into the unit (launchd and systemd start with a minimal one, which would not
find `npx`). Re-run `service install` after changing your Node.js installation; it replaces the existing installation. On Windows
the process inherits your normal logon environment.

### Logs

When started by the service, state lines are appended to
`<user cache dir>/megoocolab/logs/runner.log` (`~/.cache/megoocolab/logs` on Linux,
`~/Library/Caches/megoocolab/logs` on macOS, `%LocalAppData%\megoocolab\logs` on Windows).
Every line starts with a local RFC 3339 timestamp. Each start writes
`starting megoocolab-runner <version> (pid N)`, and a failure writes `error: …` (for example
`error: not logged in …`). On Windows, the supervisor's restart lines and any crash trace are in
the same file. If `runner.log` cannot be opened, the runner writes to
`megoocolab-runner-start.log` in the temp directory (`%TEMP%` on Windows, `$TMPDIR` or `/tmp`
elsewhere).
The file is truncated at start when it exceeds 5 MiB. Interactive `run` prints to the terminal.

## Test services

A repository can declare the containers its checks need (a database, a search engine, the whole app) in
`megoocolab.toml` at its root. The runner then starts a worktree's own copy of them for one command, on free ports,
and removes them when the command ends. Two worktrees can run the same checks at the same time without sharing
anything. Docker with the Compose plugin is needed.

```toml
# megoocolab.toml
[services.test]
description = "PostgreSQL, Meilisearch and Valkey for backend pytest"
compose = ["tools/test-services/docker-compose.yml"]
ports = ["DB_PORT", "MEILI_PORT", "VALKEY_PORT"]

[services.test.env]
TEST_DATABASE_URL = "postgresql+asyncpg://megoo:megoo@localhost:${DB_PORT}/megoo_test"
MEILI_URL = "http://localhost:${MEILI_PORT}"
```

Each `[services.<name>]` table is a set:

- `compose` (required): one or more Docker Compose files, relative to `megoocolab.toml`.
- `ports`: names of variables. The runner picks a free port on 127.0.0.1 for each.
- `env`: more variables. A value may use `${NAME}` for a port, for `MEGOO_SERVICES_PROJECT` (the set's unique
  Compose project name, also usable as an image tag), or for a variable already in the environment.
- `description`: optional, one line of at most 200 characters, shown to the agent.

A set's name is a lowercase letter followed by lowercase letters and digits, with single hyphens between them, 20
characters at most. Variable names are those of environment variables; names starting with `MEGOO_SERVICES_` are
reserved. The ports, the `env` entries and `MEGOO_SERVICES_PROJECT` go both to Docker Compose (so
`"127.0.0.1:${DB_PORT}:5432"` works in a Compose file) and to the command. The runner passes its own env file to
Compose, so a `.env` beside the Compose files is never read.

```sh
megoocolab-runner services run test -- uv run pytest   # from the worktree or any folder in it
megoocolab-runner services clean                       # remove what ended checks left behind
```

`services run <name> -- <command...>` finds `megoocolab.toml` in the current folder or a parent, starts the set as
the Compose project `megoo-<folder>-<name>-<8 hex of the folder's path>` (`up -d --build --wait`), runs the command
in the current folder with the variables set, then removes the project's containers, volumes and networks and the
images its Compose files built (pulled images and Docker's build cache stay). Ctrl+C and stop signals are passed to
the command, and the set is removed afterwards. A worktree runs one check per set at a time: a second one is
refused at once.

It exits with the command's exit code, or 125 when the runner could not start or remove the services, or the set is
already running in this worktree.

Records, env files and logs are kept in `<user cache dir>/megoocolab/services` (`MEGOO_SERVICES_DIR` overrides it),
never in the worktree. When the start or the command fails, the containers' logs are saved to `logs/<project>.log`
there and the path is printed. Logs older than seven days are deleted.

Services are removed in three places, so nothing keeps running:

1. when the command ends: pass, fail, Ctrl+C or a stop signal;
2. when a run ends (success, failure or cancel), the runner removes every set its worktree still has, for example
   after a check was killed outright. What it cannot remove within two minutes stays recorded and is written to
   the runner's log;
3. when the runner starts, every hour, and before each `services run`, sets whose command is no longer running are
   removed. `services clean` does the same by hand.

Writable runs (implement, the fix roles, finish, freestyle, crons) in a worktree with `megoocolab.toml` get a
"Test services" section in their prompt. It names the sets and the command, and asks the agent to add any service,
port or variable that new work needs to the file in the same commit. The runner puts its own folder first on the
agent's `PATH` and sets `MEGOO_SERVICES_DIR`, so the agent's checks and the runner share the same records.
`megoocolab-runner services --help` prints the file's format.

The first run of a planning session gets a section too. Without `megoocolab.toml`, the planning agent is asked to
find out whether any check needs a container, and if one does, to make "Add megoocolab.toml" the plan's first step.
That step writes the file, points the repository's check instructions at `services run` and proves each set. With
the file, the agent is told that a step adding a check that needs a new service, port or variable changes the file
in that same step. Both include the file's format, because a planning run cannot run commands. A plan session
continued with an answer or a rejection, the other read-only runs and Knowledge Base drafts get nothing. To stop
the suggestion for a repository, commit an empty `megoocolab.toml`.

The runner only removes Compose projects it recorded itself, and only names of the form `megoo-…-<8 hex>`. Other
containers, such as a MegooColab instance's `megoocolab-*` containers, are never touched.

## What the runner does and does not do

- **Metadata only.** The server receives agent messages, plan entries, tool titles and
  kinds, changed file paths with line counts, the first word of commands with exit codes,
  and permission decisions. File contents, diffs and raw command output never leave your
  machine.
- **Worktrees.** Each task runs in its own git worktree at
  `<user cache dir>/megoocolab/worktrees/<agent-id>/<TASK-KEY>`, on branch
  `megoo/<TASK-KEY>-<slug>`, created from the repository path you bound to the project.
  Your working copy is not touched.
- **Policies.** `read_only` denies all writes and allows only read-only commands
  (`git status|log|diff|show|blame|grep|ls-files`, `ls`, `cat`, `rg`, ...).
  `workspace` allows reads, writes and commands only inside the worktree; anything
  resolving outside it (including `..` and symlinks) is denied. Denials are shown on the task.
- **Messages from people.** A message sent to the agent from a task reaches it in the turn it is
  working on, without stopping it, through the ACP steering extension (`_session/steering`,
  which the Claude Code and Codex adapters support). With an adapter that lacks it, or when no
  turn is running, the agent gets the message at its next run.
- **Isolation.** Your own Claude settings cannot pre-approve tools for MegooColab runs.
- **Not a sandbox.** The runner's before/after git check (risk R1) is a best-effort check of what a
  run changed. It is there to catch adapters or settings that bypass the runner's permission
  requests. An agent that can run arbitrary commands, for example through a bypassed adapter,
  can still evade it, such as by tampering with git state the runner trusts. `workspace` runs
  can execute commands in the worktree by design.
- It never runs anything unless your account's agent is assigned a run by someone
  allowed to use it (owner, project manager or admin).
- **Run token.** A workflow run gets its own MCP token. It is valid only while that run is
  running and is scoped to one task and one role. The runner keeps it out of its run log
  and out of everything it sends to the server. The Claude adapter, however, passes it to
  the `claude` process on its command line, where any local user can read it while the run
  lasts (on Linux and macOS by default; on Windows, processes of the same user). Not
  verified for the Codex adapter.
