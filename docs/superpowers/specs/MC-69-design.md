# MC-69 design: the runner gets `megoocolab.toml` created as a plan step, and reminds agents to keep it up to date

## Goal

When a task is planned in a repository that has no `megoocolab.toml` and whose checks need containers, the plan gets a first step that creates the file, so you approve it with the plan. Once the file exists, agents are reminded in every task to update it whenever new tests or commands need a service it does not declare. Mockup v2 shows both flows.

## Decisions

- **Created as a step in the task's plan** (your answer). The runner tells the planning agent the file is missing; the agent adds the step only when a check needs a container; you approve it with the plan; it is built and reviewed as its own commit. Rejected: creating it right away inside any writable run (arrives unannounced in a task about something else), and a task of its own on the board (needs server and web app changes, and checks keep sharing containers until it is merged).
- **Kept up to date** (your instruction of 18:50 UTC). Two reminders:
  - the planning agent is told that a step adding a check or a command that needs a new service, port or variable changes the file in that same step;
  - every writable run gets one more sentence in today's "Test services" section saying the same for its own work. This covers fix runs, freestyle chats and crons, which have no plan.
- **The file's format does not change.** It declares services (Compose files, ports, variables), not check commands. I read "new commands or tests require adding" as: a new check that needs a set, a port or a variable the file lacks. Check commands stay in the repository's own instructions (AGENTS.md, README), which the creating step updates. If you meant that the file should also list the commands, reject this design and say so: that is a format change.
- **Only the runner changes**, as in MC-52: the server does not know the file. The runner reads the worktree and adds text to the prompt.
- **The agent decides whether containers are needed**, from the repository itself (Compose files, CI configuration, README, test settings). If no check needs one, no step is added and nothing is created.
- **The format is written once** in the runner and used in three places: the two planning sections and `megoocolab-runner services --help`. A planning run is read-only and cannot run the command, so it gets the text in its prompt; writable runs are pointed to the command.
- **The planning section is added only to a new session.** A session resumed with your answer or your rejection already has it, so a rejection such as "drop that step" is not contradicted by a repeated instruction.

## Architecture

All in `runner/`:

- `internal/services/prompt.go`
  - `Format` (new constant): the file's format in about ten lines, taken from the runner README's "Test services" section (the keys, the name rules, `${NAME}`, the reserved `MEGOO_SERVICES_` prefix, that a `.env` is not read).
  - `PlanSection(worktree)` (new): the text for a planning run, one of three:
    - **no file**: the repository has no `megoocolab.toml`; what the file gives (each worktree's own containers per check, on free ports, removed afterwards); find out how the checks get their services; if any check needs a container, make "Add megoocolab.toml" the plan's first step and say in the plan that the runner asked for it, not the design; the step writes the file (and a Compose file for the checks if the repository has none that fits), changes the repository's instructions for running checks to use `megoocolab-runner services run <name> -- <command>`, and proves each set by running its check through it; later steps run those checks the same way; if no check needs a container, add no step. Then `Format`.
    - **file with sets**: the set names and descriptions, as today's section lists them; steps run commands that need them through `services run`; a step that adds a check or a command needing a service, a port or a variable the file does not declare changes `megoocolab.toml`, its Compose files and the repository's instructions in that same step. Then `Format`.
    - **file with no sets**: the same rule, saying the file declares no services yet. No creation step is suggested.
  - `PromptSection(worktree)` (changed): the existing section for writable runs gets the sentence "If your work adds a check or a command that needs a service, a port or a variable the file does not declare, add it to `megoocolab.toml` (and its Compose files) in the same commit, and run the new check through it. `megoocolab-runner services --help` describes the file." A worktree without the file, or with no sets, still gets nothing.
- `internal/jobs/manager.go`: next to today's call for writable runs, a read-only run with `role == "plan"` on a new session gets `PlanSection`. An error is written to the run's log and the run goes on, as today.
- `cmd/services.go`: the `services` command's long help shows `Format`.
- `runner/README.md`: the paragraph on what runs are told, in "Test services".

## Data and interfaces

- **No change** to the file's format, the server protocol, the database, the API or the web app. `role` is already sent in `run_start`; the runner starts using it.
- **New prompt text** for planning runs; one new sentence for writable runs.
- **`megoocolab-runner services --help`** prints the format.

## Error handling and edge cases

- **An invalid `megoocolab.toml`:** the error goes to the run's log and no section is added, as today. Text of an error never reaches a prompt.
- **What reaches the prompt from the file** stays as in MC-52: set names (checked against the name rule) and descriptions (one line, 200 characters at most).
- **You do not want the step:** reject the plan and say so. To stop the suggestion for a repository for good, commit an empty `megoocolab.toml`.
- **Two tasks planned before either is merged** both get the step. The second to merge has a conflict in the file, which the finish stage resolves like any other conflict.
- **Docker is missing on the runner's computer:** the step cannot prove the file; `services run` says so and the implementing agent asks you, as with any failing check.
- **The reviewers:** the step is in the approved plan and marked as asked for by the runner, so the step review and the final review do not treat it as work nobody asked for.
- **Other read-only runs** (brainstorm, the reviews, pull-request review) and Knowledge Base draft runs get nothing.
- **A plan session started by an older runner and resumed by the new one** does not get the section. It gets it at the next task.

## Testing

Tests are written first.

- **`runner/internal/services`** (`prompt_test.go`): the exact text of `PlanSection` for no file, a file with sets, a file with no sets, an invalid file (error, no text) and a file only in a parent folder (counts as no file); the new sentence in `PromptSection`; `Format` names every key the loader accepts.
- **`runner/internal/jobs`** (`services_test.go`, with the fake agent):
  - a read-only run with role `plan` gets the "no file" section in a worktree without the file, and the "keep it up to date" section with it;
  - read-only runs with another role, or none, get nothing;
  - a resumed plan session gets nothing;
  - a writable run with the file gets the new sentence, and one without the file still gets nothing.
- **`runner/cmd`:** `services --help` prints the format.
- **By hand before merging:** plan a task in a repository without the file whose tests need a database, and see the step in the plan; plan one in a repository whose tests need nothing, and see no step; in this repository, plan a task that adds a check needing a new service, and see the change to `megoocolab.toml` in that step.

## Out of scope

- Creating the file outside a plan: freestyle chats, crons and fix runs do not create it. They only keep an existing one up to date.
- Listing check commands in `megoocolab.toml`, or any other change to its format.
- Anything in the server or the web app: no setting, no notice that a project has no file, no task created automatically.
- Telling the brainstorm stage, so that designs mention the file.
- Checking by program whether the file is out of date. The agents are reminded; nothing enforces it.
- Adding the file to the other projects by hand: each gets it with its next planned task that needs it.
