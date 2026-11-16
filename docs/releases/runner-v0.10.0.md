`megoocolab-runner` 0.10.0 keeps the background service running on Windows, restarting the runner after a crash, and says in `runner.log` why it didn't start when it can't.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.
- **macOS:** run `megoocolab-runner service install` once after updating, so the service gets the new restart rules below.

## New

- **Windows restarts the runner after a crash.** At sign-in, the startup entry now starts a hidden supervisor that starts the runner and starts it again if it crashes: after 5 seconds at first, then waiting longer each time, up to 2 minutes. It doesn't restart a runner you stopped, or one that stopped because it needs `login` again.
  - Task Manager therefore shows two `megoocolab-runner.exe` processes. `service stop` stops both.
  - The runner still starts only after you sign in: a computer waiting at the sign-in screen (for example after Windows Update) has no runner.

## Improved

- **`service install` does the whole job.** It refuses until `login` has been done, then registers the service, starts the runner and shows `service status`. Running it again replaces the installation. `service start` does nothing when the runner is already running, so the commands shown in MegooColab still work.
- **`runner.log` says what happened.** Every line starts with the time. Each start writes `starting megoocolab-runner <version> (pid N)`, and a failure to start writes `error: …`, for example `error: not logged in …`. On Windows, the supervisor's restarts and any crash trace go to the same file. If `runner.log` can't be opened, the runner writes to `megoocolab-runner-start.log` in the temp folder.
- **`service status` on Windows warns when autostart is broken:** it shows the stored startup command, and says so when that file no longer exists or the entry was disabled in Task Manager → Startup apps. `service install` turns a disabled entry back on.

## Fixed

- **The runner no longer stays in a console window at sign-in on Windows,** for example when Windows Terminal is the default console. The startup entry now always moves the runner to a hidden process; a brief console flash is still possible.
- **A missing or broken `runner.json` no longer makes the service restart forever.** The runner exits with status 78, as for a revoked token, and the service waits for `login`.
- **macOS no longer restarts the runner in a loop when it needs `login`.** launchd still restarts it after a crash, but a runner whose token was revoked or replaced, or that isn't logged in, now stays down until `login` and `service start`.
- **On Linux, `service install` replaces a unit that systemd had marked as failed.**

Runner 0.10.0 works with any MegooColab server.
