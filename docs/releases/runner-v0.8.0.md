`megoocolab-runner` 0.8.0 gives agents **secrets** as environment variables and runs **agent crons**, the two features MegooColab 0.12.0 brings.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## New

### Secrets
- **Secrets become environment variables of the agent.** The secrets MegooColab sends with a run are set in the agent's environment, so the commands it runs and the MCP servers it starts can use them by name.
  - **Kept in memory only:** values arrive with the run's start and are never written to disk.
- **Values never go back.** Before the runner sends MegooColab anything, it replaces every secret value with `[NAME]`, including trimmed, JSON-escaped and URL-encoded forms. That covers messages, tool calls and results, plans, file changes, summaries, errors and steer results. Values shorter than 4 characters are left alone.
- **Protected variables:** the runner never lets a secret replace a variable it or the agent program relies on (`PATH`, `HOME`, `MEGOO…`, the agent programs' own settings), or one that would make a shell run code or send traffic through a proxy, even if the server sent it.

### Crons
- **A throwaway copy for each cron.** A cron's run works in a folder the runner keeps for that cron, separate from your own checkout.
  - **Before each run:** the runner fetches the project's default branch from `origin` with the machine's own git credentials and resets the folder to it. If `origin` can't be reached, it uses the last fetched commit.
  - **After each run:** whatever the run changed or committed is thrown away.
  - **Old folders:** the folders of crons unused for 30 days are removed.
- **Commits are reported.** The runner tells MegooColab the commit a cron run worked on, and if the run made a commit of its own, so MegooColab can fail that run.

### Capabilities
The runner tells MegooColab it can take secrets (`secrets/1`) and run crons (`crons/1`).

Runner 0.8.0 also works with older MegooColab servers, which simply send no secrets and no crons.
