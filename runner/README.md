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

The manifest's version and hashes are placeholders: Scoop's `checkver -u` /
autoupdate fills them in from the first `runner-v*` release (the release workflow does
not edit the manifest).

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
Only one runner connection per user is live; starting a second one replaces the first.

### Run in the background

```sh
megoocolab-runner service install   # no admin rights needed
megoocolab-runner service start
megoocolab-runner service status
megoocolab-runner service stop
megoocolab-runner service uninstall
```

The service runs as you, because the adapters need your agent logins and repositories.
`service install` only registers it; run `service start` to start it now.

- **Linux:** a systemd user unit, enabled for `default.target`, so it starts when your user
  manager does. Run `loginctl enable-linger $USER` once to keep it running when you are
  logged out. When the server ends the session for good (the token was revoked, or another
  runner signed in with your account) the runner exits with status 78 and systemd does not
  restart it: run `login` again, then `service start`.
- **macOS:** a LaunchAgent in `~/Library/LaunchAgents`, loaded at login.
- **Windows:** an `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` entry that starts `megoocolab-runner run --background`
  at logon; it restarts itself once without a console window, so you may see a brief console flash at logon. `service start` launches it detached right away,
  `service stop` asks it to cancel its runs and exit (and ends it after 15 s if it does
  not), `service status` shows `running (pid N)`, `stopped` or `not installed`.
  Windows has no crash restart for this: after a crash it comes back at the next logon or
  with `service start`.

No admin rights are needed on any OS. On Linux and macOS, `service install` captures your
current `PATH` into the unit (launchd and systemd start with a minimal one, which would not
find `npx`). Re-run `service install` after changing your Node.js installation; it replaces the existing installation. On Windows
the process inherits your normal logon environment.

### Logs

When started by the service, state lines are appended to
`<user cache dir>/megoocolab/logs/runner.log` (`~/.cache/megoocolab/logs` on Linux,
`~/Library/Caches/megoocolab/logs` on macOS, `%LocalAppData%\megoocolab\logs` on Windows).
The file is truncated at start when it exceeds 5 MiB. Interactive `run` prints to the terminal.

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
- **Isolation.** Your own Claude settings cannot pre-approve tools for MegooColab runs.
- It never runs anything unless your account's agent is assigned a run by someone
  allowed to use it (owner, project manager or admin).
