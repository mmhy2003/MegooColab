# MC-52 design: the runner gives every worktree its own test services, and removes them after each check

## Goal

Any project can declare the services its checks need (Docker Compose files) in a file in its repository. An agent, or a person, then runs each check through the runner, which starts that worktree's own containers on free ports, runs the check, and removes the containers as soon as it ends. Tasks working at the same time no longer share containers, so they cannot block or break each other, and nothing stays running afterwards.

## What changed from the rejected design

The first design was a Python tool for this repository only. Following your instruction of 14:16 UTC, this is now a MegooColab feature built into the runner, for every project. This repository becomes its first user.

## Decisions

- **A feature of the runner, for all projects** (your instruction). Rejected: a tool that lives only in this repository.
- **Declared in a file in the repository** (your answer): `megoocolab.toml` at the repository root. Each branch carries the definition that fits its code, and it works outside MegooColab runs too. Rejected: a Services tab in the project's settings, and showing the file in the app. Nothing changes in the backend or the web app.
- **Containers live only while a check runs** (your instruction of 14:00 UTC). The agent wraps each check: `megoocolab-runner services run <name> -- <command>`. Rejected: starting them when a run starts and removing them when it ends. They would sit idle while the agent writes code, and images built at the start would not hold the agent's changes.
- **Three layers of removal**, so nothing is left behind:
  1. when the command ends: pass, fail, Ctrl+C or a stop signal;
  2. when the run ends, the runner removes whatever that worktree still has (a check that was killed outright);
  3. when the runner starts, every hour, and before every `services run`, it removes services whose command is no longer running.
- **Docker Compose, described by data, not by start and stop commands.** The runner builds the `docker compose` calls itself, so they work the same on Windows and Linux, and removal never depends on a project's own stop script.
- **TOML**, because the runner already reads TOML (no new dependency).
- **The runner tells the agent.** When a writable run's worktree has `megoocolab.toml`, the runner adds a short section to the prompt naming the service sets and the command. The server does not know the file, and projects without it get no extra text.
- **One check per service set per worktree at a time.** A second one is refused at once, so nothing waits on anything.

## Architecture

### The file

```toml
# megoocolab.toml
[services.test]
description = "PostgreSQL, Meilisearch and Valkey for backend pytest"
compose = ["tools/test-services/docker-compose.yml"]
ports = ["DB_PORT", "MEILI_PORT", "VALKEY_PORT"]

[services.test.env]
TEST_DATABASE_URL = "postgresql+asyncpg://megoo:megoo@localhost:${DB_PORT}/megoo_test"
MEILI_URL = "http://localhost:${MEILI_PORT}"
```

- `compose`: one or more Compose files, relative to the file.
- `ports`: names of variables. The runner finds a free port on 127.0.0.1 for each.
- `env`: more variables. A value may use `${NAME}` for a port, for `MEGOO_SERVICES_PROJECT` (the unique Compose project name, also usable as an image tag), or for a variable already in the environment (a project secret, for example).
- `description`: optional, one line, shown to the agent.

The ports and `env` go to Docker Compose (so `"127.0.0.1:${DB_PORT}:5432"` works in a Compose file) and to the check command.

### The command (new: `runner/cmd/services.go`, `runner/internal/services/`)

`megoocolab-runner services run <name> -- <command...>`:

1. Finds `megoocolab.toml` in the current folder or a parent. That folder is the worktree.
2. Names the Compose project `megoo-<folder>-<name>-<8 hex of the folder's full path>`, for example `megoo-mc-52-e2e-3fa9c1d2`.
3. Removes services whose command is gone (layer 3). Refuses if this worktree is already running `<name>`.
4. Picks the ports, writes a record and an env file in the runner's cache folder (never in the worktree), and runs `docker compose -p <project> --env-file <file> -f ... up -d --build --wait`. Passing its own env file means a `.env` beside the Compose files is never read.
5. Runs the command in the folder it was called from, with the variables set, passing input and output through.
6. On a failed start or a failed command, saves the containers' logs in the cache folder and prints the path.
7. Removes the project's containers, volumes and networks, and the images the Compose files built (images that were pulled stay; Docker's build cache stays, so the next build is quick). Deletes the record.
8. Exits with the command's exit code.

`megoocolab-runner services clean` removes every service set left by commands that are no longer running.

### In a run (changed: `runner/internal/jobs/manager.go`, `adapter.go`)

- **Prompt.** For writable runs (implement, the fix roles, finish, freestyle, crons), when the worktree has `megoocolab.toml` with services, the runner appends:

  > ## Test services
  > This repository declares services for its checks in `megoocolab.toml`: `test` (PostgreSQL, Meilisearch and Valkey for backend pytest), `e2e` (…). Run every command that needs them as `megoocolab-runner services run <name> -- <command>`. It starts this worktree's own containers on free ports, gives your command the variables the file defines, and removes the containers when the command ends. Do not start, stop or reuse the project's containers any other way, and never touch containers you did not start.

  Read-only runs (brainstorm, plan, the reviews) cannot run commands and get nothing.
- **Environment.** The runner puts its own folder first on the agent's `PATH`, so the command is found, and sets `MEGOO_SERVICES_DIR` to its cache folder, so the command and the runner share one set of records. Secrets cannot override `MEGOO*` names.
- **End of run** (layer 2). After the agent has exited, on success, failure or cancel, and before the run is reported finished, the runner removes every recorded service set of that worktree. It has two minutes; what it cannot remove stays recorded for layer 3 and is written to the runner's log.
- **Runner start and every hour** (layer 3), next to the existing sweep of old draft folders.

### This repository as the first user

- `megoocolab.toml` with three sets:
  - `test`: database, search and Valkey for `pytest`;
  - `migrate`: the same containers, with `DATABASE_URL` and `DEV_DATABASE_URL` on a scratch database;
  - `e2e`: `deploy/docker-compose.yml` + `deploy/docker-compose.build.yml`, unchanged. Its `env` holds what `.superpowers/e2e.env` held, with `HTTP_PORT`, `PUBLIC_URL` and `E2E_BASE_URL` on the free port and `MEGOO_VERSION=${MEGOO_SERVICES_PROJECT}`. Today every local build is tagged `latest`, so two builds at once can start each other's code.
- `tools/test-services/docker-compose.yml` (new): pgvector, Meilisearch and Valkey with health checks, data in memory, ports from the variables. It is outside `deploy/`, so it asks for no app release.
- `AGENTS.md`:
  - backend: `megoocolab-runner services run test -- uv run pytest`;
  - migrations: `megoocolab-runner services run migrate -- ...`;
  - browser tests: `megoocolab-runner services run e2e -- npx playwright test --reporter=line`.

  The rules "never start a second pytest run", "stop the dev Caddy first" and "use `megoo_migrate` in the dev Postgres" go. The Docker safety rule becomes: only through `services run`, plus the dev containers.
- `README.md` (the test sections) and `runner/README.md` (a "Test services" section with the file format).

## Data and interfaces

- **File:** `megoocolab.toml`, table `services.<name>` with `compose` (required), `ports`, `env`, `description`. Names: a lowercase letter, then up to 19 lowercase letters, digits or hyphens. Variable names: as environment variables; `MEGOO*` is reserved.
- **Commands:** `services run <name> -- <command...>` and `services clean`.
- **Variables the command gets:** each port, each `env` entry, and `MEGOO_SERVICES_PROJECT`.
- **Records:** `<runner cache>/services/<project>.json` (project, worktree, set name, Compose files, built images, process id, start time), plus `<project>.env` and `logs/<project>.log`. Logs older than seven days are deleted by the sweep.
- **Exit codes:** the command's own; 125 when the runner could not start or remove the services, or the set is already running.
- **No change** to the server protocol, the database, the API or the web app.

## Error handling and edge cases

- **No `megoocolab.toml`, an unknown set, a bad file, or a Compose file missing:** a one-line error naming the file and the key; nothing is started.
- **Docker is missing or not running:** says so; nothing is started.
- **The start fails** (build error, a container never healthy): logs saved, everything removed, exit 125.
- **A picked port is taken before the containers bind it:** the start is retried with new ports, three times at most.
- **Ctrl+C or a stop signal:** passed to the command, then everything is removed.
- **The command is killed outright:** the services stay until layer 2 or 3 removes them. A later `services run` of the same set in that worktree removes them first.
- **A run is cancelled, or the runner shuts down:** layer 2 runs. If the runner exits before it finishes, layer 3 does it at the next start.
- **Removal fails:** the record stays, the error is printed and logged, and every later sweep tries again.
- **Safety:** the runner only ever removes Compose projects it recorded, and only names of the form `megoo-…-<8 hex>`. `megoocolab-*` (a real instance), `megoocolab-dev-*` and anything else can never match. A test proves it.
- **Several runners on one machine** (the browser tests start their own): each keeps its records in its own cache folder, so none removes another's services.
- **Two worktrees with the same folder name:** the path hash keeps their projects apart.
- **The text from the file that reaches the prompt** is only the set names (checked against the name rule) and descriptions (one line, 200 characters at most).

## Testing

Tests are written first.

- **`runner/internal/services`** (Docker replaced by a fake `docker` program built like the fake agent, which records each call):
  - the file: valid, invalid, unknown keys, bad names;
  - project names: stable, unique per path, valid for Compose;
  - `${NAME}` expansion and port picking;
  - the order of calls, and removal after a failing command, a failed start and a signal;
  - the exit code is the command's;
  - a second run of the same set is refused;
  - the sweep removes only records whose command is gone, and never a name outside the pattern.
- **`runner/internal/jobs`** (with the fake agent):
  - a writable run in a worktree with the file gets the section, and can call the command by name;
  - a read-only run, and a worktree without the file, get nothing;
  - services left by a killed check are removed when the run ends and when it is cancelled.
- **`runner/cmd`:** the two commands and their errors.
- **Real Docker, in CI on Linux:** one test starts a one-container set, checks that the command saw its port, and checks that no container, volume or network is left.
- **By hand before merging, in this repository:**
  - `services run test -- uv run pytest -q -n auto` in two worktrees at the same time, both green;
  - a migration generated and checked with `migrate`;
  - the whole browser suite with `services run e2e` while a second worktree runs one spec, the dev Caddy left running;
  - kill a check and see the next one, and the end of the run, remove its containers;
  - `docker ps -a` shows no `megoo-…` container afterwards.

## Out of scope

- Anything in the web app or the server: no settings tab, no status on the task page, no report of which projects have services.
- Service managers other than Docker Compose.
- A limit on how many worktrees run checks at once: each set lives only while its check runs.
- Keeping services running between checks, or for debugging.
- Adding `megoocolab.toml` to other projects: each does that in a task of its own.
- Running the browser tests in CI.
