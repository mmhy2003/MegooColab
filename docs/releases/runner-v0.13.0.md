`megoocolab-runner` 0.13.0 keeps its agents' runs going through a short disconnect from the server, instead of stopping them all at once.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## New

- **Runs survive a short disconnect.** When the connection to the server drops, the runner keeps its runs going for the grace period the server gives it (60 seconds by default), reconnects quickly, and tells the server which runs it still holds. If it can't reconnect in time, it stops them as before.

## Fixed

- When the server gives up on a run and starts a new one for the same task, the runner now stops the old run first, so the two never work in the same worktree at once.
- While the connection is down, a run's progress waits on the runner and is sent in order once it reconnects. A run's end is never dropped.

Runner 0.13.0 works with any MegooColab server. The grace period needs MegooColab 0.30.0. With an older server, the runner stops its runs when the connection drops, as before.
