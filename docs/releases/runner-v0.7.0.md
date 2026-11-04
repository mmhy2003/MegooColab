`megoocolab-runner` 0.7.0 lets agents **write Knowledge Base drafts** with people, which MegooColab 0.11.0 brings.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## New

- **A folder for each draft.** An agent writing a Knowledge Base draft works in a folder the runner keeps for that draft, so the agent picks up its session from one request to the next.
  - **A project's draft:** a read-only copy of the project's repository at its current commit, so the agent can read the code. No branch is made in your repository.
  - **A team's or the organization's draft:** an empty folder.
- **The folder is removed** when the draft is saved or discarded. If the runner was away at the time, it removes the folders of drafts unused for 30 days.
- **Tells MegooColab it can write drafts** (`drafts/1`), so people can pick its agents in **Write with an agent**. With an older runner, the agent is listed as needing an update.

Runner 0.7.0 also works with older MegooColab servers, which simply send no drafts.
