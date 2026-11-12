`megoocolab-runner` 0.8.1 keeps Claude Code's commands in the foreground, so an agent waits for a long test suite instead of ending its run before the suite finishes.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## Fixed

- **Claude Code waits for long commands.**
  - **What went wrong:** Claude Code allows a command 10 minutes in the foreground. A longer test suite went to the background, the agent ended its turn to wait for it, and the run ended with the turn. The tests stopped unread, and the step was left unfinished.
  - **Now:** the runner starts Claude Code with background commands turned off. A command can run for up to 3 hours, or 30 minutes when the agent sets no limit of its own. A command that reaches its limit is stopped and the agent sees that it failed, instead of the command being moved to the background.
  - **Only runs are affected.** The settings apply to the Claude Code that the runner starts, not to your own Claude Code. Codex and OMP agents are unchanged.

Runner 0.8.1 works with any MegooColab server. With MegooColab 0.18.2 or later, agents are also told in their instructions to wait for long commands in the foreground.
