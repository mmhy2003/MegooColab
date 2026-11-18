`megoocolab-runner` 0.12.0 helps agents set up and keep up to date the `megoocolab.toml` file that gives a repository's checks their own test containers.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## New

- **Plans now include adding `megoocolab.toml` when a repository needs it.** In a repository without the file, the first run of a planning session is asked whether any check needs a container, such as a database or a search engine. If one does, the plan's first step becomes "Add megoocolab.toml": it writes the file, points the repository's check instructions at `megoocolab-runner services run` and makes sure each set starts.
  - In a repository that already has the file, the planning agent is told that a step adding a check that needs a new service, port or variable changes the file in that same step.
  - The planning prompt includes the file's format, since planning runs can't run commands.
  - To stop the suggestion for a repository, commit an empty `megoocolab.toml`.
- **`megoocolab-runner services --help` shows the format of `megoocolab.toml`:** the keys of a set, the naming rules, `${NAME}` references and the reserved `MEGOO_SERVICES_` prefix.

## Improved

- **Writable runs keep `megoocolab.toml` up to date.** Their "Test services" section now asks the agent to add any service, port or variable that new work needs to the file in the same commit.

Runner 0.12.0 works with any MegooColab server.
