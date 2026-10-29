The first release of `megoocolab-runner`: the small program that runs your coding agents (Claude Code and Codex) on your own computer for MegooColab. Your code never leaves your machine.

## Install

- **macOS and Linux:** `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`
- **Windows (Scoop):** `scoop install https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/scoop/megoocolab-runner.json`
- **Manually:** download the archive for your system below and check it against `checksums.txt`.

Then:

```sh
megoocolab-runner login --url https://your-megoocolab --token <a runner token from Access tokens>
megoocolab-runner doctor
megoocolab-runner run
```

## New

- Runs work assigned to your agents. Each task gets its own git worktree and branch (`megoo/<TASK-KEY>-<slug>`), so your working copy is never touched.
- Starts each task from a freshly fetched branch: the repository's default branch, or the one the task names in "Branch from".
- Takes part in the full workflow (Brainstorm, Design, Plan, Build, Review), including live design mockups and read-only sessions that answer questions about your code.
- Reports metadata only:
  - sent to the server: agent messages, plan steps, tool names, changed file paths with line counts, and command names with exit codes;
  - never sent: file contents, diffs and command output.
- Permission policies:
  - `read_only` allows reading only;
  - `workspace` allows changes inside the task's worktree and nowhere else. Anything denied is shown on the task.
- Repairs a task's worktree when its `.git` file goes missing or gets damaged, keeping the agent's uncommitted work.
- Runs in the background as your user on Linux (systemd), macOS (LaunchAgent) and Windows (logon entry), with no admin rights: `megoocolab-runner service install`, then `service start`.
- `megoocolab-runner doctor` checks your settings, the server, Node.js, git and the agent adapters.
- Builds for Windows, macOS and Linux, on amd64 and arm64.
