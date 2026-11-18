# MC-69 implementation plan: planning runs are told to add `megoocolab.toml`, and every run is reminded to keep it up to date

**Goal:** a new planning session in a worktree without `megoocolab.toml` is told to make "Add megoocolab.toml" the plan's first step when a check needs containers. A planning session in a worktree with the file, and every writable run, is told to change the file in the same step or commit that adds a check needing a new service, port or variable.

**Architecture:** only the runner changes. `runner/internal/services/prompt.go` gets the `Format` constant, a new `PlanSection(worktree)` and one more sentence in `PromptSection`. `runner/internal/jobs/services.go` gets one helper, `servicesPrompt`, that picks the section for a run (writable: `PromptSection`; read-only, role `plan`, not a continued session: `PlanSection`; others: nothing). `manager.go` calls it in place of today's inline block. `megoocolab-runner services --help` prints `Format`. The README says what runs are told.

## Conventions for every step

- Work on the existing branch `megoo/MC-69-megoocolab-toml-creation`. One commit per step, subject `type(area): what changed (MC-69)` (AGENTS.md "Commits"), body in plain sentences, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/`.
- TDD: write the test, run it and see it fail (a compile error for a new symbol counts), implement, run it again. Commands run from `runner/`. Before each commit, `go test ./...` and `go vet ./...` pass in `runner/`.
- Do not change `runner/VERSION`. No change to the backend, the frontend, the server protocol or the file's format. No new dependency.

## One point the design left open, decided here

**What "a new session" means.** `openSession` (`internal/jobs/session.go`) can start a new session for a run that asked to resume one (`fresh`, or after a failed resume). That new session gets the full prompt plus the resume prompt (an answer or a rejection). The planning section is therefore added only when `rs.ResumeSessionID == ""`: the plan stage's first run. A continued run gets nothing, whether the resume works or falls back. This way a rejection such as "drop that step" is never followed by a repeated instruction to add it, which is the design's reason for the rule.

## File map

| File | Change |
|---|---|
| `runner/internal/services/prompt.go` | `Format` (new), `PlanSection` (new), `loadOwn` and `setList` (new private helpers taken from `PromptSection`), the reminder sentence added to `PromptSection`. |
| `runner/internal/services/prompt_test.go` | Tests for `Format`, `PlanSection` and the new sentence. |
| `runner/cmd/services.go` | `Long` help of the `services` command shows `Format`. |
| `runner/cmd/services_test.go` | `services --help` test. |
| `runner/internal/jobs/services.go` | `rolePlan` constant and `servicesPrompt` helper. |
| `runner/internal/jobs/manager.go` | Line ~959: `text := sess.prompt + servicesPrompt(rs, kind, wt, logf)` replaces the inline `PromptSection` block. |
| `runner/internal/jobs/services_test.go` | Plan-role, other-role, resumed-session and writable-sentence tests. |
| `runner/README.md` | "Test services": the paragraph on what runs are told. |

## Code the steps share

### `Format` (step 1, `runner/internal/services/prompt.go`)

```go
// Format is megoocolab.toml's format, for agents: a planning run gets it in its
// prompt, and `megoocolab-runner services --help` shows it to writable runs.
const Format = `megoocolab.toml, at the repository's root, declares the containers the checks need. Each [services.<name>] table is a set:
- compose (required): one or more Docker Compose files, relative to megoocolab.toml.
- ports: names of variables. The runner picks a free port on 127.0.0.1 for each.
- env: more variables. A value may use ${NAME} for a port, for MEGOO_SERVICES_PROJECT (the set's unique Compose project name, also usable as an image tag), or for a variable already in the environment.
- description: optional, one line of at most 200 characters, shown to agents.
A set's name is a lowercase letter followed by lowercase letters and digits, with single hyphens between them, 20 characters at most. Variable names are those of environment variables; names starting with MEGOO_SERVICES_ are reserved.
The ports, the env entries and MEGOO_SERVICES_PROJECT go both to Docker Compose (so "127.0.0.1:${DB_PORT}:5432" works in a Compose file) and to the command. A .env file beside the Compose files is never read.
Example:

    [services.test]
    description = "PostgreSQL for the backend tests"
    compose = ["tools/test-services/docker-compose.yml"]
    ports = ["DB_PORT"]

    [services.test.env]
    DATABASE_URL = "postgresql://test:test@localhost:${DB_PORT}/test"

Run a check with its set as: megoocolab-runner services run <name> -- <command>
`
```

### `prompt.go` after step 2

```go
// keepUpToDate ends a writable run's section.
const keepUpToDate = "If your work adds a check or a command that needs a service, a port or a variable the file does not " +
	"declare, add it to `megoocolab.toml` (and its Compose files) in the same commit, and run the new check through it. " +
	"`megoocolab-runner services --help` describes the file."

// planKeep is the planning rule once the file exists.
const planKeep = "A step that adds a check or a command needing a service, a port or a variable the file does not declare " +
	"changes `megoocolab.toml`, its Compose files and the repository's instructions for running checks in that same " +
	"step, and runs the new check through `megoocolab-runner services run`."

// planNoFile is the planning text for a repository without the file.
const planNoFile = "This repository has no `megoocolab.toml`. With one, the runner gives each worktree its own copy of the " +
	"containers a check needs (a database, a search engine, the whole app) on free ports, and removes them when the " +
	"check ends, so the checks of different tasks never share containers.\n" +
	"Find out how this repository's checks get their services: Compose files, the CI configuration, the README, the " +
	"test settings. If any check needs a container, make \"Add megoocolab.toml\" the plan's first step, and say in the " +
	"plan that the runner asked for this step, not the design. That step writes `megoocolab.toml` (and a Compose file " +
	"for the checks if the repository has none that fits), changes the repository's instructions for running its " +
	"checks (AGENTS.md, README or the like) to use `megoocolab-runner services run <name> -- <command>`, and proves " +
	"each set by running its check through it. Later steps run those checks the same way. If no check needs a " +
	"container, add no step."

// PromptSection is the text a writable run's prompt gets about the worktree's
// service sets: "" when the worktree has no megoocolab.toml or it declares no
// set. Only the worktree's own file counts, not one in a parent folder.
func PromptSection(worktree string) (string, error) {
	f, err := loadOwn(worktree)
	if err != nil || f == nil || len(f.Sets) == 0 {
		return "", err
	}
	return "\n\n## Test services\nThis repository declares services for its checks in `megoocolab.toml`: " +
		setList(f) +
		". Run every command that needs them as `megoocolab-runner services run <name> -- <command>`. " +
		"It starts this worktree's own containers on free ports, gives your command the variables the file defines, " +
		"and removes the containers when the command ends. Do not start, stop or reuse the project's containers any " +
		"other way, and never touch containers you did not start. " + keepUpToDate + "\n", nil
}

// PlanSection is the text a planning run's prompt gets about megoocolab.toml:
// how to add it in a worktree without one, how to keep it up to date in one
// with it, then the file's format. Only the worktree's own file counts.
func PlanSection(worktree string) (string, error) {
	f, err := loadOwn(worktree)
	if err != nil {
		return "", err
	}
	var body string
	switch {
	case f == nil:
		body = planNoFile
	case len(f.Sets) == 0:
		body = "This repository has a `megoocolab.toml` that declares no services yet. " + planKeep
	default:
		body = "This repository declares services for its checks in `megoocolab.toml`: " + setList(f) +
			". Steps run every command that needs them as `megoocolab-runner services run <name> -- <command>`. " + planKeep
	}
	return "\n\n## Test services\n" + body + "\n\n" + Format, nil
}

// loadOwn loads the worktree's own megoocolab.toml, not one in a parent
// folder: nil, nil when it has none.
func loadOwn(worktree string) (*File, error) {
	path := filepath.Join(worktree, FileName)
	if _, err := os.Stat(path); errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	return Load(path)
}

// setList names the sets for a prompt: `name` (description), sorted.
func setList(f *File) string {
	sets := make([]string, 0, len(f.Sets))
	for _, name := range f.Names() {
		s := "`" + name + "`"
		if d := f.Sets[name].Description; d != "" {
			s += " (" + d + ")"
		}
		sets = append(sets, s)
	}
	return strings.Join(sets, ", ")
}
```

### `servicesPrompt` (step 3, `runner/internal/jobs/services.go`)

```go
// rolePlan is the workflow role of a planning run (RunStart.Role).
const rolePlan = "plan"

// servicesPrompt is what a run's prompt gets about megoocolab.toml: a writable
// run the "Test services" section, the first run of a planning session the
// planning one, other runs (drafts, the other read-only roles, a continued
// planning session) nothing. An invalid file goes to the run's log and the
// run gets nothing.
func servicesPrompt(rs protocol.RunStart, kind policy.Kind, wt string, logf io.Writer) string {
	var section func(string) (string, error)
	switch {
	case rs.Draft != nil:
		return ""
	case kind == policy.Workspace:
		section = services.PromptSection
	case kind == policy.ReadOnly && rs.Role == rolePlan && rs.ResumeSessionID == "":
		section = services.PlanSection
	default:
		return ""
	}
	text, err := section(wt)
	if err != nil {
		fmt.Fprintf(logf, "runner: services: %v\n", err)
	}
	return text
}
```

In `manager.go` (around line 959) this:

```go
	text := sess.prompt
	if kind == policy.Workspace && rs.Draft == nil {
		section, err := services.PromptSection(wt)
		if err != nil {
			fmt.Fprintf(logf, "runner: services: %v\n", err)
		}
		text += section
	}
```

becomes `text := sess.prompt + servicesPrompt(rs, kind, wt, logf)`. Remove the `services` import from `manager.go` only if nothing else there uses it (`go build` says so).

## Steps

### 1. feat(runner): `services --help` shows megoocolab.toml's format

- **Tests first.**
  - `runner/internal/services/prompt_test.go`: add `TestFormatNamesEveryKey`. It goes over `reflect.TypeOf(setDoc{})` fields and reads each `toml` tag (`description`, `compose`, `ports`, `env`). For each tag it checks that `Format` contains `"- " + tag + ":"`, and that `Format` contains `[services.<name>]`, `${NAME}`, `MEGOO_SERVICES_`, `.env` and `megoocolab-runner services run <name> -- <command>`. A key added to the loader later then fails this test until `Format` documents it.
  - `runner/cmd/services_test.go`: add `TestServicesHelpShowsTheFormat`. `err, stdout, _ := runServices(t, "services", "--help")`, then `err == nil` and `strings.Contains(stdout, strings.TrimSpace(services.Format))`. Cobra trims trailing whitespace of `Long`, hence `TrimSpace`.
- Run `go test ./internal/services/ ./cmd/ -run 'TestFormatNamesEveryKey|TestServicesHelpShowsTheFormat'`. Expected: compile error, `undefined: Format`.
- **Implement.** Add `Format` to `prompt.go` exactly as in "Code the steps share". In `cmd/services.go` `newServicesCmd`, add `Long: "Start a worktree's test services for one command.\n\n" + services.Format,`.
- Run the same command: it passes. Then `go test ./...` and `go vet ./...`.
- Commit: `feat(runner): services --help shows megoocolab.toml's format (MC-69)`.

### 2. feat(runner): planning text for megoocolab.toml and the keep-it-up-to-date sentence

- **Tests first** in `runner/internal/services/prompt_test.go`. Reuse the `write` helper in `TestPromptSection` by moving it to a top-level `writeFile(t, dir, name, content)` in that file.
  - `TestPromptSection/sets`: `want` gets `" " + keepUpToDate` before the final `"\n"`. Write the sentence out literally in the test, not the constant: `"... never touch containers you did not start. If your work adds a check or a command that needs a service, a port or a variable the file does not declare, add it to `megoocolab.toml` (and its Compose files) in the same commit, and run the new check through it. `megoocolab-runner services --help` describes the file.\n"`. The other subtests stay as they are.
  - New `TestPlanSection` with subtests. Each subtest compares with `"\n\n## Test services\n" + body + "\n\n" + Format`, with `body` written out literally:
    - `no file`: empty `t.TempDir()`, body is the `planNoFile` text.
    - `sets`: the same two-set file as `TestPromptSection/sets`. Body: "This repository declares services for its checks in `megoocolab.toml`: `e2e`, `test` (Postgres for the backend tests). Steps run every command that needs them as `megoocolab-runner services run <name> -- <command>`. " + the planKeep text.
    - `no sets`: file `# nothing yet\n`. Body: "This repository has a `megoocolab.toml` that declares no services yet. " + the planKeep text. It must not contain `Add megoocolab.toml`.
    - `invalid file`: `[services.test]\ncompose = ["missing.yml"]\n`. Expect `""` and a non-nil error.
    - `only in a parent folder`: as in `TestPromptSection`. Expect the `no file` text and a nil error.
- Run `go test ./internal/services/ -run 'TestPromptSection|TestPlanSection'`. Expected: compile error `undefined: PlanSection`, and `sets` would fail on the missing sentence.
- **Implement** `prompt.go` as in "`prompt.go` after step 2". Add the `keepUpToDate`, `planKeep` and `planNoFile` constants, plus `PlanSection`, `loadOwn` and `setList`, and rewrite `PromptSection` on top of the helpers.
- Run again: pass. `go test ./...` (the jobs tests check only `Contains`, so they still pass) and `go vet ./...`.
- Commit: `feat(runner): planning text for megoocolab.toml and a reminder to keep it up to date (MC-69)`.

### 3. feat(runner): planning runs get the megoocolab.toml section

- **Tests first** in `runner/internal/jobs/services_test.go`. Use the existing helpers: `newEnvWithCache`, `commitFiles`, `servicesFiles`, `startRunWith`, `finished`, `readReport`, `finalReport`, and `twoTurns` from `resume_test.go`.
  - `TestPlanRunGetsThePlanSection`, with subtests `without the file` and `with the file`. Each runs `startRunWith("run-1", "MEG-1", func(rs) { rs.Policy = "read_only"; rs.Role = "plan" })` and expects outcome `completed`. Then:
    - without the file: `Prompts[0]` contains "This repository has no `megoocolab.toml`" and `Add megoocolab.toml`;
    - with the file (`commitFiles(t, e.repo, servicesFiles)` first): `Prompts[0]` contains "`test`" and "changes `megoocolab.toml`".
    - Both: `Prompts[0] == "please" + want`, where `want, _ := services.PlanSection(e.worktree("MEG-1"))`.
  - `TestOtherReadOnlyRunsGetNoPlanSection`: a table of roles `""`, `"brainstorm"`, `"final_review"`, `"pr_review"`, all read-only with no file. `Prompts[0]` must not contain `## Test services`.
  - `TestContinuedPlanSessionGetsNoSection`: `t.Setenv("FAKEAGENT_SESSIONS_DIR", t.TempDir())`, with `twoTurns`.
    - run-a: read-only, role plan, `Prompt = "first turn"`, no file. Its prompt contains `## Test services`.
    - run-b: read-only, role plan, `ResumeSessionID = *first.SessionID`, `ResumePrompt = "continue please"`. Prompts are exactly `["continue please"]`.
    - Subtest `fallback`: read-only, role plan, `Prompt = "full prompt"`, `ResumePrompt = "continue please"`, `ResumeSessionID = "fake-session-404"`. Prompts are exactly `["full prompt\n\ncontinue please"]`.
  - In `TestWritableRunGetsTheServicesSection`, also require "`megoocolab-runner services --help` describes the file". `TestReadOnlyRunAndRunsWithoutTheFileGetNoSection` stays and covers a writable run without the file.
- Run `go test ./internal/jobs/ -run 'Plan|TestWritableRunGetsTheServicesSection'`. Expected: the plan subtests fail (no section).
- **Implement** `rolePlan` and `servicesPrompt` in `internal/jobs/services.go` (code in "Code the steps share"; add imports `protocol` and `policy`). Replace the block in `manager.go` with `text := sess.prompt + servicesPrompt(rs, kind, wt, logf)`.
- Run again: pass. `go test ./...` and `go vet ./...`.
- Commit: `feat(runner): planning runs are told to add or update megoocolab.toml (MC-69)`.

### 4. docs(runner): README says what planning and writable runs are told about megoocolab.toml

- In `runner/README.md` "Test services", replace the paragraph that starts "Writable runs (implement, the fix roles, finish, freestyle, crons) in a worktree with `megoocolab.toml`..." and ends "Read-only runs get nothing." with:

  > Writable runs (implement, the fix roles, finish, freestyle, crons) in a worktree with `megoocolab.toml` get a "Test services" section in their prompt. It names the sets and the command, and asks the agent to add any service, port or variable that new work needs to the file in the same commit. The runner puts its own folder first on the agent's `PATH` and sets `MEGOO_SERVICES_DIR`, so the agent's checks and the runner share the same records. `megoocolab-runner services --help` prints the file's format.
  >
  > The first run of a planning session gets a section too. Without `megoocolab.toml`, the planning agent is asked to find out whether any check needs a container, and if one does, to make "Add megoocolab.toml" the plan's first step. That step writes the file, points the repository's check instructions at `services run` and proves each set. With the file, the agent is told that a step adding a check that needs a new service, port or variable changes the file in that same step. Both include the file's format, because a planning run cannot run commands. A plan session continued with an answer or a rejection, the other read-only runs and Knowledge Base drafts get nothing. To stop the suggestion for a repository, commit an empty `megoocolab.toml`.
- No test; check with `go test ./...` that nothing else changed.
- Commit: `docs(runner): what planning and writable runs are told about megoocolab.toml (MC-69)`.

## Final verification

From `runner/`:

```bash
go vet ./...
go test ./...
go run . services --help        # prints the format
```

By hand before merging (from the design; needs a runner built from the branch and the server, outside an agent session):
- plan a task in a repository without the file whose tests need a database: the plan's first step is "Add megoocolab.toml", marked as asked for by the runner;
- plan one in a repository whose tests need nothing: no such step;
- in this repository, plan a task that adds a check needing a new service: that step changes `megoocolab.toml`.
