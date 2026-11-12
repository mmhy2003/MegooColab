`megoocolab-runner` 0.8.2 tells MegooColab whether an agent left changes uncommitted, so files git ignores no longer make finished work look unfinished.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## Fixed

- **Ignored files no longer count as uncommitted work.**
  - **What went wrong:** at the end of a run, the runner told MegooColab only whether the run had changed anything in the folder, including files git ignores. MegooColab 0.18.1 and 0.18.2 read that as "left uncommitted", so a run that created or removed a `__pycache__` folder was sent back to commit work that was already committed.
  - **Now:** the runner also reports whether `git status` shows changes nobody committed when the run ends. Ignored files and the `.megoocolab/` folder are left out. The existing report is unchanged and still drives the read-only check.

Runner 0.8.2 works with any MegooColab server: it sends the new report only to a server that asks for it, which MegooColab 0.18.3 and later do.
