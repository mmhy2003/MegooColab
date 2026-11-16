# MC-2: Runner service that comes back, and says why when it doesn't

## Goal

After `megoocolab-runner service install` on Windows, the runner starts at every logon, restarts after a crash, and leaves a readable trace in `runner.log` whenever it cannot start. `service status` says when autostart is broken. Two small service bugs on Linux and macOS are fixed along the way.

Nothing was reproduced on a Windows machine, so the design removes each suspected cause instead of depending on which one is real. The checks on the reporter's machine are listed under Testing.

## Decisions

| Decision | Why | Rejected |
|---|---|---|
| **Restart on Windows with a built-in supervisor process** (your answer). | No admin rights, same on every Windows version, testable in CI. | A Task Scheduler logon task: the repo already dropped `schtasks /SC ONLOGON` in 163647f, and registering it without admin is unverified. No restart at all. |
| **`service install` refuses without a usable login, then registers and starts the runner** (your answer). Same on all three OSes. | "Install didn't work" was often "login was never done" or "nobody ran `service start`". | Warn only; register only. |
| **Linux and macOS minor fixes are included** (your answer). | | Splitting macOS into its own task. |
| **The Run-key process always relaunches hidden.** The console-visibility test (`GetConsoleWindow` + `IsWindowVisible`) is deleted. | Only the Run key starts `run --background` without the marker variable, so no test is needed. This covers the Windows Terminal case without reproducing it. | Detecting "parent is Explorer". |
| **`service start` succeeds when the runner is already running.** | The web app shows `service install; service start` and must keep working with old and new runners. The frontend is not changed. | Changing the frontend snippets. |
| **An unusable config exits with 78, like a revoked token.** | Otherwise the new supervisor (and systemd today) restarts forever on something only `login` can fix. | Keep exit 1. |
| **`service install` re-enables a startup entry that was disabled in Task Manager.** | Running install is an explicit request to start at logon. | Only warning about it. |
| **Log lines get a timestamp.** | Without one, nobody can tell whether a line is from this morning's logon. | |

## Architecture

### 1. Logging first (all OSes) — `runner/cmd/run.go`, new `runner/cmd/runlog.go`

In service mode (`--background`, or not interactive) `run` opens `runner.log` **before anything else**, including the hidden relaunch and `config.Load()`.

- Every line written to the log is prefixed with a local RFC 3339 timestamp.
- The first line is `starting megoocolab-runner <version> (pid N)`.
- The final error is written as `error: …` before the process exits.
- If `runner.log` cannot be opened, the runner falls back to `<temp dir>/megoocolab-runner-start.log`, best effort.

### 2. Three roles on Windows — `run.go`, `service_proc.go`, `service_windows.go`

`run --background` picks its role from `MEGOOCOLAB_RUNNER_HIDDEN` (pure function `backgroundRole`):

| Marker | Role | What it does |
|---|---|---|
| unset | launcher (started by the Run key) | Starts the supervisor hidden (`CREATE_NO_WINDOW`, marker `1`) and exits 0. |
| `1` | supervisor (also what `service start` spawns) | Writes the pid file, runs the worker in a loop. |
| `worker` | worker | Today's runner: loads the config, connects, watches the stop file. It no longer touches the pid file. |

On Linux and macOS `--background` stays a single process, as today.

### 3. Supervisor loop — new `runner/cmd/supervise.go` (platform independent, dependencies injected)

- Exits at once with a log line if the pid file already names another live runner.
- Starts the worker with stdout and stderr pointed at `runner.log`, so panic traces are kept. The worker does not print its final error to stderr a second time.
- After the worker exits:
  - status 0 (deliberate stop) or 78 (needs `login`): the supervisor logs why and exits;
  - anything else: logs `runner exited with status N; restarting in Xs` and restarts.
- Delay: 5 s, doubling to a cap of 120 s; back to 5 s once a worker stayed up 5 minutes.
- The stop file is checked before every start and every second while waiting, so `service stop` works during a backoff.
- `service stop` is unchanged: stop file, 15 s wait, then `taskkill /T` on the supervisor's pid, which takes the worker and the adapters with it.

### 4. `service install`, `start`, `status` — `service.go`, `service_windows.go`, `service_proc.go`

Shared command code in `service.go`:

- `install` and `start` first call `config.Load()`. On failure: `not logged in; run: megoocolab-runner login --url URL --token TOKEN`, and nothing is registered or started.
- `install` = register, start, then print the status text.
- `start` on a running service prints `already running` and exits 0.

Windows `Install()` stops a running runner, writes the Run value and deletes the entry's value under `…\Explorer\StartupApproved\Run`.

Windows `Status()` keeps its first line (`running (pid N)`, `stopped`, `not installed`) and adds lines:

```
stopped
autostart: "C:\Users\me\scoop\apps\megoocolab-runner\current\megoocolab-runner.exe" run --background
warning: that file does not exist, so the runner will not start at logon; run `megoocolab-runner service install` again
warning: the startup entry is disabled (Task Manager → Startup apps); enable it there or run `megoocolab-runner service install`
```

Pure helpers in `service_proc.go`: `runValueExe(value)` (the quoted first token) and `startupDisabled(bytes)` (first byte odd means disabled; a missing value means enabled). The failed-start message of `service start` points to the log file instead of "run it in a terminal".

### 5. Exit codes — `root.go`

- An unusable config joins `ErrUnauthorized` and `ErrReplaced`: exit 78.
- On macOS in service mode, 78 becomes 0 (see 7). Pure function over (error, OS, interactive) so it is testable.

### 6. Linux — `service_other.go`

`libManager.Install()` stops and uninstalls whenever the status is anything but "not installed", including the error kardianos returns for a `failed` unit. Re-running `service install` then works in that state.

### 7. macOS — `service.go`

`serviceConfig` passes a custom `LaunchdConfig`: kardianos' v1.3.0 plist with `KeepAlive` as `{SuccessfulExit = false}`, and `RunAtLoad` true. launchd then restarts after a crash but not after exit 0, which is what the runner now returns when only `login` can help. Existing installs get this by re-running `service install`.

### 8. Docs — `runner/README.md` (Service mode, Logs), `docs/install.md` step 6

- `service install` checks the login and starts the runner.
- The Windows supervisor, the two processes in Task Manager, and what `service status` reports.
- Stated plainly: on Windows the runner starts only after you sign in; a machine waiting at the sign-in screen has no runner.
- The log format, the fallback log file, and that macOS users re-run `service install` once.

## Error handling and edge cases

- **Supervisor killed alone:** the worker keeps running, `status` says `stopped`. A later `service start` starts a new pair and the server replaces the old worker, which exits 78. Not handled further.
- **Crash loop:** `status` shows `running` (the supervisor is alive); the log shows the restarts.
- **Run value edited by hand** into an unexpected shape: `status` prints it and skips the file check.
- **Scoop:** the stored path is expected to go through the `current` junction and survive `scoop update`. If it does not, `status` now says so.
- **macOS:** a plain `kill` (SIGTERM) now leaves the runner down until `service start` or the next login, because it exits 0.
- **Old plist or old Run value with the new binary:** behaves as before the change, never worse.

## Testing

Unit tests, run by CI on Linux, Windows and macOS:

- `backgroundRole`, `runValueExe`, `startupDisabled`, the extended status text.
- The supervisor loop with a fake worker and clock: restart on 1, stop on 0 and 78, delay growth, cap and reset, stop file during backoff, a second supervisor refusing to start.
- The log writer: timestamp prefix, error line, fallback file; a missing config leaves a line in the log.
- Exit codes: config error gives 78, macOS service mode gives 0.
- The install flow with a fake manager: refuses without login, installs then starts, `start` is a no-op when running.
- `libManager.Install` with a fake kardianos service whose status errors.
- The launchd template contains `SuccessfulExit` and no plain `KeepAlive` boolean.

Manual, on the reporter's Windows 11 machine (the cause is still unconfirmed):

1. Before updating: note `service status`, the Run value and whether the file exists, the Startup apps state, and the default terminal setting.
2. After updating: `service install`, restart, sign in. Expect `running`, and timestamped lines from logon in `runner.log`.
3. Repeat with "Windows Console Host" and with "Windows Terminal" as the default terminal.
4. End the worker process in Task Manager: it is back within seconds.
5. Disable the entry in Startup apps: `service status` warns.

The `StartupApproved` byte rule and the macOS plist are checked by unit tests only; the plist is not verified on a real Mac in this task.

## Out of scope

- Running before sign-in on Windows (a real service or a boot task needs admin rights).
- Removing the brief console flash at logon.
- Tying the worker's life to the supervisor with a job object.
- Scoop update while the runner is running, and any change to the Scoop manifest.
- Frontend changes, version bumps and release notes (done at release time; the runner note must tell macOS users to re-run `service install`).
- macOS restart throttling, and showing `failed` in `service status` on Linux.
