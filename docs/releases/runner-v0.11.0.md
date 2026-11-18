`megoocolab-runner` 0.11.0 starts each worktree's own test containers for an agent's checks, on free ports, and removes them when the check ends, so two agents can run the same tests at the same time without getting in each other's way.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## New

- **A repository can declare the containers its checks need.** Put a `megoocolab.toml` at the repository's root, with one `[services.<name>]` table per set: the Docker Compose files to start, the port variables the runner fills with free ports, and any other variables the checks need. The runner README's "Test services" section describes the format.
  - Docker with the Compose plugin is needed on the runner's computer.
- **`megoocolab-runner services run <name> -- <command>` runs a check on its own containers.** It starts the worktree's copy of the set, runs the command with the ports and variables set, and then removes the containers, volumes, networks and the images it built, whether the command passed, failed or was stopped with Ctrl+C. It exits with the command's exit code, or 125 when the services couldn't be started or removed.
  - When the start or the command fails, the containers' logs are saved and their path is printed.
  - A worktree runs one check per set at a time; a second one is refused at once.
- **Agents are told about the test services.** Writable runs (implement, the fix roles, finish, freestyle, crons) in a worktree with `megoocolab.toml` get a "Test services" section in their prompt that names the sets and the command to use. Read-only runs get nothing.
- **Nothing is left running.** Besides the command's own clean-up, the runner removes a worktree's remaining sets when its run ends, and every hour and at start it removes sets whose command is no longer running. `megoocolab-runner services clean` does the same by hand. The runner only ever removes Compose projects it started itself.

Runner 0.11.0 works with any MegooColab server.
