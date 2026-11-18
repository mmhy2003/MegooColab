# MC-52 implementation plan: the runner gives every worktree its own test services, and removes them after each check

**Goal:** `megoocolab-runner services run <name> -- <command>` starts the services a repository declares in `megoocolab.toml` as this worktree's own Docker Compose project on free ports, runs the command with the variables, then removes everything. Runs get told about it in their prompt, and leftovers are removed at the end of each run and by an hourly sweep. This repository becomes its first user.

**Architecture:** a new Go package `runner/internal/services` holds everything: the file (`config.go`), names and variables (`naming.go`, `expand.go`, `ports.go`), records and removal (`record.go`, `remove.go`, `alive_*.go`), starting a set (`start.go`), the wrapper (`run.go`) and the prompt text (`prompt.go`). It calls `docker` through one helper (`docker.go`). `runner/cmd/services.go` is the thin CLI. `runner/internal/jobs` adds the prompt section, the agent's `PATH` and `MEGOO_SERVICES_DIR`, the end-of-run removal (layer 2) and the hourly sweep (layer 3). Tests replace Docker with a fake `docker` program, `runner/internal/fakedocker`, built the way the fake agent is built. One real-Docker test runs in CI on Linux.

## Conventions for every step

- Branch `megoo/MC-52-tests-checks-improvement`. One commit per step, subject `type(area): what changed (MC-52)` (AGENTS.md "Commits"), ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/`.
- TDD: write the test, run it and see it fail (a compile error for a new symbol counts), implement, run it again. Commands run from `runner/` unless stated. Before each commit, `go test ./...` and `go vet ./...` pass in `runner/`.
- Do not change `runner/VERSION` (AGENTS.md: versions change only in the release commit). No backend, frontend or server protocol change.
- No new Go dependency: TOML is `github.com/pelletier/go-toml/v2` (already in `go.mod`), Windows calls use `golang.org/x/sys/windows` (already there).
- Code must build and its tests must pass on Linux, macOS and Windows (the CI matrix). Unix-only behaviour (signals) is in tests that call `t.Skip` on Windows.

## Two points the design left open, decided here

1. **Reserved variable names.** The design says "`MEGOO*` is reserved" for variable names in the file, and also puts `MEGOO_VERSION=${MEGOO_SERVICES_PROJECT}` in this repository's `e2e` set. Both cannot hold. This plan reserves only the names the runner sets itself: any name starting with `MEGOO_SERVICES_` (compared without case). `MEGOO_VERSION` is then allowed, as the design's own `e2e` example needs. Secrets keep their existing rule (`jobs/secrets.go` already refuses every `MEGOO*` secret), so "Secrets cannot override `MEGOO*` names" holds unchanged.
2. **`HTTPS_PORT` in `e2e`.** `deploy/docker-compose.yml` publishes `${HTTPS_PORT:-443}:443` as well as `HTTP_PORT`. Two worktrees would fight over 443, so the `e2e` set lists both `HTTP_PORT` and `HTTPS_PORT` as ports. The Compose files stay unchanged.

## File map

| File | New/changed | Responsibility |
|---|---|---|
| `runner/internal/fakedocker/main.go` | new | Fake `docker` for tests: logs each call, scripted failures |
| `runner/internal/fakedocker/fakedocker_test.go` | new | Its own tests |
| `runner/internal/testutil/build.go` | changed | `BuildFakeDocker` (a folder holding `docker`/`docker.exe`), `BuildRunner` (`megoocolab-runner`) |
| `runner/internal/services/config.go` (+`_test`) | new | `FileName`, `Set`, `File`, `Find`, `Load`, validation |
| `runner/internal/services/naming.go` (+`_test`) | new | `Canonical`, `ProjectName`, `IsOurs` |
| `runner/internal/services/expand.go` (+`_test`) | new | `Expand`, `Vars` |
| `runner/internal/services/ports.go` (+`_test`) | new | `PickPorts` |
| `runner/internal/services/docker.go` | new | `docker(...)` helper, `Check` |
| `runner/internal/services/record.go` (+`_test`) | new | `Record`, `Dir`, `Claim`, `Save`, `List`, `ErrBusy` |
| `runner/internal/services/alive_unix.go`, `alive_windows.go` | new | `alive(pid)` |
| `runner/internal/services/remove.go` (+`_test`) | new | `Remove`, `CleanWorktree`, `Sweep` |
| `runner/internal/services/start.go` (+`_test`) | new | `start` (ports, env file, built images, `up` with retries), `saveLogs` |
| `runner/internal/services/run.go` (+`_test`) | new | `Options`, `Run`, `ExitServices` |
| `runner/internal/services/helper_test.go` | new | `TestMain` helper modes for the services tests |
| `runner/internal/services/prompt.go` (+`_test`) | new | `PromptSection` |
| `runner/internal/services/docker_test.go`, `testdata/real/*` | new | Real-Docker test (CI, Linux) |
| `runner/internal/services/repo_file_test.go` | new | This repository's `megoocolab.toml` loads |
| `runner/cmd/services.go` (+`_test`) | new | `services run`, `services clean` |
| `runner/cmd/root.go` | changed | Register `services`; `exitError` handling in `Execute` |
| `runner/cmd/run.go` | changed | `mgr.Log = out` |
| `runner/internal/fakeagent/scenario.go`, `main.go` | changed | `run` step: runs a program in the agent's cwd |
| `runner/internal/jobs/manager.go` | changed | `Executable`, `Log` fields; env; prompt section; layer 2 defer; start the sweep |
| `runner/internal/jobs/services.go` (+`_test`) | new | `servicesEnv`, `removeServices`, `sweepServices` |
| `.github/workflows/ci.yml` | changed | Real-Docker test step on Linux |
| `megoocolab.toml` | new | Sets `test`, `migrate`, `e2e` |
| `tools/test-services/docker-compose.yml`, `tools/test-services/initdb/01-migrate.sql` | new | pgvector, Meilisearch, Valkey for checks |
| `AGENTS.md`, `README.md`, `runner/README.md` | changed | Docs |

## Contracts (shared by all steps)

### Package `services` public API

```go
package services

const FileName = "megoocolab.toml"
const ExitServices = 125 // the runner could not start or remove the services, or the set is already running

// config.go
type Set struct {
	Name        string
	Description string
	Compose     []string          // absolute, cleaned paths, in file order
	Ports       []string          // variable names, in file order
	Env         map[string]string // values as written, before ${...} expansion
}
type File struct {
	Path string // absolute path of megoocolab.toml
	Dir  string // Canonical(its folder): the worktree
	Sets map[string]Set
}
func (f *File) Names() []string // sorted set names
var ErrNoFile = errors.New("no megoocolab.toml in this folder or any parent")
func Find(start string) (string, error) // start, then each parent; error wraps ErrNoFile
func Load(path string) (*File, error)

// naming.go
func Canonical(path string) string        // filepath.Abs, then EvalSymlinks (keep Abs if it fails), Clean; lower-cased on Windows
func ProjectName(worktree, set string) string
func IsOurs(project string) bool

// expand.go
func Expand(s string, lookup func(string) (string, bool)) (string, error)
func Vars(set Set, ports map[string]int, project string, lookup func(string) (string, bool)) ([]string, error) // sorted NAME=VALUE

// ports.go
var PickPorts = pickPorts // func(n int) ([]int, error); tests may replace it

// record.go
type Record struct {
	Project  string    `json:"project"`
	Worktree string    `json:"worktree"` // Canonical
	Set      string    `json:"set"`
	Compose  []string  `json:"compose"`
	EnvFile  string    `json:"env_file"`
	Built    []string  `json:"built"`
	PID      int       `json:"pid"`
	Started  time.Time `json:"started"`
}
var ErrBusy = errors.New("already running in this worktree")
func Dir() (string, error) // $MEGOO_SERVICES_DIR, else <os.UserCacheDir()>/megoocolab/services
func Claim(dir string, rec Record) error
func Save(dir string, rec Record) error
func List(dir string) ([]Record, error)

// remove.go
func Remove(ctx context.Context, dir string, rec Record) error
func CleanWorktree(ctx context.Context, dir, worktree string) error
func Sweep(ctx context.Context, dir string, now time.Time) error

// docker.go
func Check(ctx context.Context) error

// run.go
type Options struct {
	Dir     string   // records folder (Dir())
	Cwd     string   // where megoocolab.toml is searched from and the command runs
	Set     string
	Command []string // program and arguments
	Stdin   io.Reader
	Stdout  io.Writer
	Stderr  io.Writer
	Signals <-chan os.Signal // forwarded to the command; may be nil
}
func Run(ctx context.Context, o Options) int // exit code

// prompt.go
func PromptSection(worktree string) (string, error) // "" and nil when the worktree has no file or no sets
```

### Files on disk (in `dir`)

- `<dir>/<project>.json`: the `Record` (mode 0600).
- `<dir>/<project>.env`: the env file, one `NAME='value'` per line, sorted (0600; can hold expanded secrets).
- `<dir>/logs/<project>.log`: the containers' logs after a failed start or a failed command.

### Names

- Set name: `^[a-z][a-z0-9-]{0,19}$`.
- Variable name (ports and `env` keys): `^[A-Za-z_][A-Za-z0-9_]*$`. Names starting with `MEGOO_SERVICES_` (case-insensitive) are reserved. A name may not be both a port and an `env` key, and ports are unique.
- Project: `megoo-<folder>-<set>-<hash>`. `<folder>` is the base name of `Canonical(worktree)`, lower-cased, every run of characters outside `[a-z0-9]` replaced by one `-`, trimmed of `-`, cut to 24 characters (trimmed of `-` again), `wt` when empty. `<hash>` is the first 8 hex digits of SHA-256 of `Canonical(worktree)`. Example: `megoo-mc-52-e2e-3fa9c1d2`.
- `IsOurs`: `^megoo-[a-z0-9]+(-[a-z0-9]+)*-[0-9a-f]{8}$`. `megoocolab`, `megoocolab-dev`, `megoocolab-dev-db-1`, `megoo-e2e` and `megoo-x-e2e-1234567` never match.

### Errors and output

- Every message `services` prints starts with `megoocolab-runner services: `. A file error is one line: `<path of megoocolab.toml>: services.<set>.<key>: <problem>` (for example `…/megoocolab.toml: services.test.ports: "MEGOO_SERVICES_X" is reserved`).
- Compose output goes to the caller's stderr, so the command's stdout stays the command's own.

### Docker calls (all through `docker.go`, `exec.LookPath("docker")` each time, `cmd.Dir = dir` so no stray `compose.yaml` in the caller's folder is picked up, env = `os.Environ()` + the set's vars)

`compose` base arguments, called `C` below: `compose -p <project> --env-file <envfile> -f <compose1> -f <compose2> …`.

| When | Arguments |
|---|---|
| Check | `compose version`, then `info --format {{.ServerVersion}}` |
| Built images | `C config --format json`. For each service with a `build` key: its `image`, else `<project>-<service>`. Deduplicated, sorted. |
| Start | `C up -d --build --wait --wait-timeout 300` |
| Logs | `C logs --no-color --timestamps` into `logs/<project>.log` |
| Remove | `C down --volumes --remove-orphans --timeout 10` (when all Compose files and the env file still exist; otherwise `compose -p <project> down --volumes --remove-orphans --timeout 10`), then by label `com.docker.compose.project=<project>`: `ps -aq --filter label=…` → `rm -f -v <ids>`, `volume ls -q --filter label=…` → `volume rm -f <names>`, `network ls -q --filter label=…` → `network rm <ids>`, then `image rm <built…>` (an answer containing `No such image` is success). |

### Prompt section (exact text; `<sets>` is the sets in `Names()` order, each `` `name` `` followed by ` (description)` when it has one, joined by `, `)

```
\n\n## Test services\nThis repository declares services for its checks in `megoocolab.toml`: <sets>. Run every command that needs them as `megoocolab-runner services run <name> -- <command>`. It starts this worktree's own containers on free ports, gives your command the variables the file defines, and removes the containers when the command ends. Do not start, stop or reuse the project's containers any other way, and never touch containers you did not start.\n
```

### Fake docker (`runner/internal/fakedocker/main.go`)

- Each call appends one JSON line to `$FAKEDOCKER_LOG`: `{"args":[...],"env":{...}}`, where `env` holds the value of each name listed in `$FAKEDOCKER_SHOW` (comma-separated) that is set.
- The verb is `args[0]` for plain docker (`info`, `ps`, `rm`, `volume`, `network`, `image`), and for `compose` the first argument after `compose` that is not a flag or a flag's value (`-p`, `-f`, `--env-file`, `--project-directory` take a value).
- `$FAKEDOCKER_FAIL`: comma-separated verbs that print `fakedocker: <verb> failed` to stderr and exit 1.
- `$FAKEDOCKER_PORT_TAKEN=N`: the first N `up` calls print `Error response from daemon: Bind for 127.0.0.1:5432 failed: port is already allocated` and exit 1 (counter in the file `$FAKEDOCKER_LOG.up`).
- `config`: prints `$FAKEDOCKER_CONFIG`, default `{"name":"x","services":{}}`.
- `ps`, `volume ls`, `network ls`: print `leftover1` when `$FAKEDOCKER_LEFTOVER=1`, otherwise nothing.
- `logs`: prints `fake logs`. Anything else: exit 0.
- `$FAKEDOCKER_UP_SLEEP_MS`: `up` sleeps that long first (used to hold a set "running").

## Steps

### Step 1. test(runner): a fake docker program for the services tests (MC-52)

Files: `runner/internal/fakedocker/main.go` (new, `package main`), `runner/internal/fakedocker/fakedocker_test.go` (new), `runner/internal/testutil/build.go` (changed).

1. Test first, `fakedocker_test.go` (package `main_test`, like `internal/fakeagent/fakeagent_test.go`): build with `testutil.BuildFakeDocker(t)`, run `<dir>/docker` with `exec.Command(filepath.Join(dir, "docker"), …)` (`exec` finds `docker.exe` on Windows only through LookPath, so use `exec.LookPath` after putting `dir` first on a copied `PATH`, or add `.exe` when `runtime.GOOS == "windows"`). Tests:
   - `TestLogsEachCallWithItsArgsAndShownEnv`: `compose -p p -f a.yml up -d` with `FAKEDOCKER_SHOW=DB_PORT`, `DB_PORT=1234` → one log line with those args and `{"DB_PORT":"1234"}`.
   - `TestFailsTheNamedVerbs`: `FAKEDOCKER_FAIL=up` → `compose -p p up` exits 1 with `fakedocker: up failed`, `compose -p p down` exits 0.
   - `TestPortTakenOnlyForTheFirstUps`: `FAKEDOCKER_PORT_TAKEN=2` → first two `up` fail with `port is already allocated`, the third passes.
   - `TestConfigAndLeftovers`: `config --format json` prints `FAKEDOCKER_CONFIG`; `ps -aq` prints nothing, and `leftover1` with `FAKEDOCKER_LEFTOVER=1`.
2. Run: `go test ./internal/fakedocker/` → fails (no `BuildFakeDocker`).
3. Implement `main.go` per "Fake docker" in the plan's Contracts. In `build.go`, change `buildOnce(t, once, path, err, cmdName)` to `buildOnce(t, once, path, err, pkg, outName string)` (`pkg` like `./internal/fakeagent`, `outName` without `.exe`); keep `BuildFakeAgent` and `BuildFakeGit` working. Add:
   - `BuildFakeDocker(t testing.TB) string`: builds `./internal/fakedocker` as `docker` (`docker.exe` on Windows) and returns the **folder** holding it.
   - `BuildRunner(t testing.TB) string`: builds `.` (the module root's `main.go`) as `megoocolab-runner` (`.exe` on Windows) and returns the path.
4. Run `go test ./internal/fakedocker/ ./internal/fakeagent/ ./internal/jobs/` → pass.

Commit: `test(runner): a fake docker program for the services tests (MC-52)`.

### Step 2. feat(runner): read and check megoocolab.toml (MC-52)

Files: `runner/internal/services/config.go`, `config_test.go` (new).

1. Tests first (`package services`, temp folders with `os.WriteFile`):
   - `TestLoadValidFile`: the design's example file plus the Compose file on disk → `Sets["test"]` with `Compose` absolute, `Ports` in order, `Env` as written, `Description`; `Dir == Canonical(folder)`; `Names()` sorted.
   - `TestLoadRejects` (table): unknown top-level key, unknown key in a set (`services.test.foo`), missing `compose`, empty `compose`, Compose file missing, Compose path absolute, Compose path leaving the folder (`../x.yml`), bad set name (`Test`, `1x`, 21 characters, `a_b`), bad variable name (`1X`, `A-B`), reserved `MEGOO_SERVICES_PROJECT` and `megoo_services_x` in `ports` and in `env`, a port repeated, a name both a port and an `env` key, a description with a newline, a description over 200 characters, an `env` value with a newline, invalid TOML. Each error is one line (no `\n`) and contains the file path and the key (`services.<set>.<key>`, or the line for invalid TOML).
   - `TestFindWalksUp`: file in `root`, `Find(root/a/b)` → `root/megoocolab.toml`; no file → `errors.Is(err, ErrNoFile)`.
   - `TestLoadEmptyServices`: a file without `[services]` loads with no sets.
2. Run: `go test ./internal/services/ -run 'TestLoad|TestFind'` → fails to compile.
3. Implement per the Contracts: decode with `toml.NewDecoder(r).DisallowUnknownFields()` into `struct{ Services map[string]setDoc \`toml:"services"\` }`, `setDoc{Description string; Compose, Ports []string; Env map[string]string}` (TOML tags lower-case). Turn a `*toml.StrictMissingError` into `services.<set>.<key>: unknown key` (from `Errors[0].Key()`), and a `*toml.DecodeError` into `line N: <message>`. Compose paths are joined to the file's folder, cleaned, checked inside it (`filepath.Rel` not starting with `..`), and `os.Stat`ed. `Canonical` is needed here: implement it now in `naming.go` with its own test (`TestCanonicalResolvesSymlinks`: a symlinked folder gives the same result as its target; skip when `os.Symlink` fails).
4. Run again → pass.

Commit: `feat(runner): read and check megoocolab.toml (MC-52)`.

### Step 3. feat(runner): service project names, variables and free ports (MC-52)

Files: `naming.go` (add `ProjectName`, `IsOurs`), `naming_test.go`, `expand.go`, `expand_test.go`, `ports.go`, `ports_test.go` in `runner/internal/services/`.

1. Tests first:
   - `TestProjectNameStableAndPerPath`: the same path twice gives the same name; two folders both named `MC-52` under different parents give different names; the name matches `^[a-z0-9][a-z0-9_-]*$` (Compose's rule) and `IsOurs`; folder `My Repo!!` gives `megoo-my-repo-test-<8 hex>`; a 60-character folder is cut to 24.
   - `TestIsOursNeverMatchesOtherProjects`: false for `megoocolab`, `megoocolab-dev`, `megoocolab-dev-db-1`, `megoo-e2e`, `megoo-x-e2e-1234567`, `megoo--e2e-12345678`, `MEGOO-X-E2E-12345678`, `""`; true for `megoo-mc-52-e2e-3fa9c1d2`.
   - `TestExpand`: `${A}` and `x${A}y${B}` replaced from the lookup; an unknown `${C}` → error naming `C`; text without `${` unchanged; a lone `$` unchanged.
   - `TestVars`: a set with ports `DB_PORT`, `env` `URL = "pg://localhost:${DB_PORT}/${MEGOO_SERVICES_PROJECT}"` and `K = "${SECRET}"` (lookup gives `SECRET=s`) → sorted `DB_PORT=5000`, `K=s`, `MEGOO_SERVICES_PROJECT=<p>`, `URL=pg://localhost:5000/<p>`. An `env` value naming another `env` key → error (only ports, the project and the process environment expand). Error text: `services.<set>.env.<KEY>: ${NAME} is not a port, MEGOO_SERVICES_PROJECT or a variable in the environment`.
   - `TestPickPortsDistinctAndFree`: `PickPorts(3)` gives 3 distinct ports > 0, each can be listened on at `127.0.0.1` afterwards.
2. Run: `go test ./internal/services/ -run 'TestProjectName|TestIsOurs|TestExpand|TestVars|TestPickPorts'` → fails.
3. Implement per the Contracts. `pickPorts`: open `n` listeners on `127.0.0.1:0` at once, read their ports, close all.
4. Run again → pass.

Commit: `feat(runner): service project names, variables and free ports (MC-52)`.

### Step 4. feat(runner): records and removal of service sets (MC-52)

Files: `record.go`, `record_test.go`, `remove.go`, `remove_test.go`, `docker.go`, `alive_unix.go` (`//go:build !windows`), `alive_windows.go` in `runner/internal/services/`.

1. Tests first. A helper `fakeDocker(t) (log string)` puts `testutil.BuildFakeDocker(t)` first on `PATH` (`t.Setenv`), sets `FAKEDOCKER_LOG` to a temp file and returns it; `calls(t, log) [][]string` reads it.
   - `TestDirUsesTheEnvironment`: `MEGOO_SERVICES_DIR=x` → `x`; unset → ends with `megoocolab/services`.
   - `TestClaimRefusesALiveRecord`: `Claim` writes `<p>.json` (0600 on Unix); a second `Claim` of the same project with the record's PID alive → `errors.Is(err, ErrBusy)`; `List` returns the record.
   - `TestListSkipsForeignFiles`: a file `megoocolab-dev.json` with `"project":"megoocolab-dev"`, and a `<p>.json` whose `project` differs from its name, are not listed.
   - `TestRemoveCallsDownThenLabelSweepThenImages`: a record with Compose files and env file on disk, `Built: ["img:p"]` → calls in order: `compose -p <p> --env-file … -f … down --volumes --remove-orphans --timeout 10`, `ps -aq --filter label=com.docker.compose.project=<p>`, `volume ls -q --filter …`, `network ls -q --filter …`, `image rm img:p`; record and env file deleted.
   - `TestRemoveWithoutComposeFilesUsesTheProjectOnly`: Compose files gone → `compose -p <p> down …` with no `-f`/`--env-file`.
   - `TestRemoveRemovesLeftovers`: `FAKEDOCKER_LEFTOVER=1` → also `rm -f -v leftover1`, `volume rm -f leftover1`, `network rm leftover1`.
   - `TestRemoveFailureKeepsTheRecord`: `FAKEDOCKER_FAIL=down,rm` with leftovers → error returned, record still there.
   - `TestRemoveRefusesNamesThatAreNotOurs`: records for `megoocolab`, `megoocolab-dev`, `megoo-e2e` → error, **no docker call at all**.
   - `TestCleanWorktreeRemovesOnlyThatWorktree`: two records (worktrees A and B, both with live PIDs) → only A's project is removed.
   - `TestSweepRemovesOnlyDeadRecords`: replace `processAlive` (a package var defaulting to `alive`) so PID 1111 is dead and 2222 alive → only 1111's set is removed; a `logs/x.log` with mtime 8 days ago is deleted, one from 1 day ago kept.
   - `TestAliveSelf`: `alive(os.Getpid())` is true; a PID from a finished `exec.Command` (e.g. `go version`) is false.
2. Run: `go test ./internal/services/ -run 'TestDir|TestClaim|TestList|TestRemove|TestClean|TestSweep|TestAlive'` → fails.
3. Implement per the Contracts. `docker.go`: `func docker(ctx context.Context, dir string, env []string, stdout, stderr io.Writer, args ...string) error` (LookPath each time; missing → `docker not found on PATH`). `Claim` uses `os.OpenFile(…, O_CREATE|O_EXCL|O_WRONLY, 0o600)`; when the file exists, it reads it: alive PID → `ErrBusy`, else an error saying an earlier check's services could not be removed. `Save` writes to a temp file and renames. `Remove` first checks `IsOurs(rec.Project)`, collects every error with `errors.Join`, and deletes the record and env file only when all succeeded. Worktrees are compared with `Canonical` (already lower-cased on Windows). `alive`: Unix `syscall.Kill(pid, 0)` is nil or `EPERM`; Windows `windows.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION…)` + `GetExitCodeProcess == 259`. `Sweep` keeps going after one failure and returns the joined errors.
4. Run again → pass.

Commit: `feat(runner): records and removal of service sets (MC-52)`.

### Step 5. feat(runner): start a worktree's service set on free ports (MC-52)

Files: `start.go`, `start_test.go`, and `Check` in `docker.go`, in `runner/internal/services/`.

Contract (unexported, used by `Run` in step 6):

```go
// start brings set up for f's worktree. On success it returns the saved record and the vars for the command.
// On failure everything it started is removed, the logs are saved when containers were started, and the error says why.
func start(ctx context.Context, dir string, f *File, set Set, stderr io.Writer) (Record, []string, error)
func saveLogs(ctx context.Context, dir string, rec Record, vars []string) (string, error)
```

Order inside `start`: `rec := Record{Project: ProjectName(f.Dir, set.Name), Worktree: f.Dir, Set: set.Name, Compose: set.Compose, EnvFile: <dir>/<p>.env, PID: os.Getpid(), Started: time.Now()}` → `Claim` → up to 3 attempts: `PickPorts(len(set.Ports))`, `Vars(...)` with `os.LookupEnv`, write the env file (`NAME='value'`; a value containing `'` → error `services.<set>.env.<KEY>: a value cannot contain a single quote`), `config --format json` → `rec.Built`, `Save`, `up` with its stderr copied both to `stderr` and to a buffer. If `up` fails and the buffer contains `port is already allocated`, `address already in use` or `Only one usage of each socket address`, and attempts are left: `Remove` and start again (re-`Claim`). Any other failure: `saveLogs`, print `megoocolab-runner services: logs saved to <path>`, `Remove`, return the error. A failed `Claim` or `Vars` starts nothing.

`Check(ctx)`: `docker` missing → `Docker is not installed (docker not found on PATH)`; `compose version` failing → `Docker Compose is not available`; `info` failing → `Docker is not running`.

1. Tests first (fake docker from step 4):
   - `TestStartCallsInOrder`: `config`, `up -d --build --wait --wait-timeout 300` with `FAKEDOCKER_SHOW=DB_PORT,MEGOO_SERVICES_PROJECT` showing the picked port and the project; env file holds `DB_PORT='…'`; the record on disk has `Built` from `FAKEDOCKER_CONFIG={"services":{"app":{"build":{}},"web":{"build":{},"image":"web:x"},"db":{"image":"postgres"}}}` = `["<p>-app","web:x"]`.
   - `TestStartRetriesATakenPort`: `FAKEDOCKER_PORT_TAKEN=2` → 3 `up` calls, success; with `=3` → error, all removed (no record).
   - `TestStartFailureSavesLogsAndRemoves`: `FAKEDOCKER_FAIL=up` → `logs/<p>.log` holds `fake logs`, a `down` call happened, no record left, stderr names the log path.
   - `TestStartRefusesWhenBusy`: an existing record with a live PID → `ErrBusy`, no docker call.
   - `TestCheckReportsMissingAndStoppedDocker`: `PATH` without docker → "not installed"; `FAKEDOCKER_FAIL=info` → "not running".
2. Run: `go test ./internal/services/ -run 'TestStart|TestCheck'` → fails.
3. Implement.
4. Run again → pass.

Commit: `feat(runner): start a worktree's service set on free ports (MC-52)`.

### Step 6. feat(runner): services.Run wraps a check and removes its services (MC-52)

Files: `run.go`, `run_test.go`, `helper_test.go` in `runner/internal/services/`.

`Run(ctx, o)`:
1. `Find(o.Cwd)`, `Load`, look up `o.Set` (unknown → `<path>: no service set "x" (sets: a, b)`); `o.Command` empty → error. Errors → print, return `ExitServices`.
2. `Check(ctx)`; then `Sweep(ctx, o.Dir, time.Now())` (an error is printed, not fatal).
3. `start(...)`. `ErrBusy` → `megoocolab-runner services: <set> is already running in this worktree`, return 125. Other errors → 125.
4. Run the command: `exec.LookPath(o.Command[0])` (missing → print, code 127), `Dir = o.Cwd`, `Env = append(os.Environ(), vars...)`, stdin/stdout/stderr from `o`. While it runs, every signal from `o.Signals` is forwarded: Unix `cmd.Process.Signal(sig)`; Windows: `os.Interrupt` is not forwarded (the console already delivered Ctrl+C), anything else → `cmd.Process.Kill()`. Code: `ExitCode()`; on Unix, killed by a signal → `128 + signal number`.
5. Code ≠ 0 → `saveLogs` and print the path.
6. `Remove` with `context.WithTimeout(context.WithoutCancel(ctx), 2*time.Minute)`. Failure → print the error and `the services stay recorded; megoocolab-runner services clean retries`, return 125.
7. Return the command's code.

`helper_test.go`: `TestMain` that, when `SERVICES_TEST_HELPER` is set, acts as the command and exits: `exit:N` → exit N; `env:NAME` → print `os.Getenv(NAME)` and exit 0; `sleep` → sleep 30 s. Otherwise `os.Exit(m.Run())`. Tests call `Run` with `Command: []string{os.Args[0]}`.

1. Tests first:
   - `TestRunPassesVarsAndExitCode`: a set with port `DB_PORT` and `env` `URL = "x:${DB_PORT}"`, `SERVICES_TEST_HELPER=env:URL` → stdout `x:<port>`, code 0, calls `up` then `down`, no record left.
   - `TestRunReturnsTheCommandsFailure`: `exit:3` → 3, logs saved, `down` called.
   - `TestRunRefusesASecondRunOfTheSameSet`: a live record already there → 125, the helper never ran (use `exit:0` and check stdout empty), no `up`.
   - `TestRunRemovesAfterASignal` (skip on Windows): `sleep`, send `syscall.SIGTERM` on `o.Signals` after `up` is in the log → returns `128+15`, `down` called.
   - `TestRunFailedStartIs125`: `FAKEDOCKER_FAIL=up` → 125, the helper did not run.
   - `TestRunRemovalFailureIs125`: `FAKEDOCKER_FAIL=down,rm`, `FAKEDOCKER_LEFTOVER=1`, `exit:0` → 125, record kept.
   - `TestRunErrorsBeforeStarting`: no file, unknown set (message lists the sets), docker missing → 125 and no `up`.
   - `TestRunSweepsDeadRecordsFirst`: a dead-PID record of another worktree is removed before `up`.
2. Run: `go test ./internal/services/ -run TestRun` → fails.
3. Implement.
4. Run again → pass; `go test ./internal/services/` all green.

Commit: `feat(runner): services.Run wraps a check and removes its services (MC-52)`.

### Step 7. feat(runner): megoocolab-runner services run and services clean (MC-52)

Files: `runner/cmd/services.go`, `runner/cmd/services_test.go` (new), `runner/cmd/root.go` (changed).

1. Tests first (`package cmd`, fake docker on `PATH`, `MEGOO_SERVICES_DIR` a temp dir, a temp folder with a `megoocolab.toml` and Compose file, `os.Chdir` is not used: the command reads `os.Getwd`, so tests use `t.Chdir(dir)` (Go 1.24+)):
   - `TestServicesRunExitsWithTheCommandsCode`: `newRootCmd("test")`, `SetArgs([]string{"services","run","test","--","git","--version"})` → `Execute` returns nil; with `git definitely-not-a-git-command` → an error `e` with `errors.As(e, &exitError{})` and code 1.
   - `TestServicesRunNeedsADash`: `services run test git` (no `--`) → a usage error saying `use: megoocolab-runner services run <name> -- <command...>`; `services run -- git` (no name) → same.
   - `TestServicesClean`: one dead-PID record → `services clean` prints `removed <project>` and the record is gone; a `FAKEDOCKER_FAIL=down,rm` + leftover failure → `exitError{125}`.
   - `TestExecuteExitError`: `exitCode`-style unit check that `exitError{code: 3}` maps to 3 (add a helper `exitStatus(err error) (int, bool)` in `root.go` that `Execute` uses).
2. Run: `go test ./cmd/ -run 'TestServices|TestExecuteExitError'` → fails.
3. Implement:
   - `type exitError struct{ code int }` with `Error()` returning `exit status N`. In `Execute`, if `errors.As(err, &exitError{})`: `os.Exit(code)` without printing (Run already printed).
   - `newServicesCmd()` (`Use: "services"`, `Short: "Start a worktree's test services for one command (megoocolab.toml)"`) with `run` (`Use: "run <name> -- <command...>"`, `Args`: `cmd.ArgsLenAtDash() == 1 && len(args) >= 2`) and `clean` (`Args: cobra.NoArgs`). `run`: `services.Dir()`, `os.Getwd()`, `signal.Notify(ch, os.Interrupt, syscall.SIGTERM)` (deferred `signal.Stop`), then `services.Run`; a non-zero code → `exitError{code}`. `clean`: `List` then `Sweep` and print each project that went away; error → print, `exitError{services.ExitServices}`.
   - Register `newServicesCmd()` in `newRootCmd`. Neither command reads `runner.json` (no login needed).
4. Run again → pass; `go run . services --help` lists `run` and `clean`.

Commit: `feat(runner): megoocolab-runner services run and services clean (MC-52)`.

### Step 8. feat(runner): runs are told about the test services and can call the command (MC-52)

Files: `runner/internal/services/prompt.go`, `prompt_test.go` (new); `runner/internal/fakeagent/scenario.go`, `main.go` (changed); `runner/internal/jobs/services.go`, `services_test.go` (new); `runner/internal/jobs/manager.go` (changed).

1. Tests first:
   - `services/prompt_test.go` `TestPromptSection`: a worktree with sets `test` (description) and `e2e` (none) → exactly the plan's "Prompt section" text with `` `e2e`, `test` (…)``; no file → `""`, nil; file with no sets → `""`, nil; an invalid file → `""` and an error.
   - fake agent: new step `{"run":{"args":["prog","a"]}}` runs `exec.CommandContext(ctx, args[0], args[1:]...)` in the agent's cwd with its environment (no permission request, like `commit`); the result has `Outcome: "exit:<code>"` (`exit:-1` when it could not start) and `Content` = combined output cut to 4,000 bytes. Add `Run *RunStep` (`RunStep{Args []string}`) and `typeName` `"run"`. Add a case to `internal/fakeagent/fakeagent_test.go` for it.
   - `jobs/services_test.go`, with a helper `commitFiles(t, repo string, files map[string]string)` (write, `git add`, commit with `-c user.name=t -c user.email=t@t`) called before `startRun`, files `megoocolab.toml` (set `test`, `compose = ["svc/compose.yml"]`, `ports = ["DB_PORT"]`) and `svc/compose.yml`. Add `Outcome string \`json:"outcome"\`` to `agentReport.Steps` in `manager_test.go`.
     - `TestWritableRunGetsTheServicesSection`: `startRun(..., "workspace")` → `readReport().Prompts[0]` contains `## Test services` and `` `test` ``.
     - `TestReadOnlyRunAndRunsWithoutTheFileGetNoSection`: `read_only` with the file, and `workspace` without it → no `## Test services`.
     - `TestRunCanCallServicesRunByName`: fake docker first on `PATH` (`t.Setenv`), `FAKEDOCKER_LOG` set, tweak `m.Executable = func() (string, error) { return testutil.BuildRunner(t), nil }`, scenario `[{"run":{"args":["megoocolab-runner","services","run","test","--","git","--version"]}}]` → step outcome `exit:0`, the fake docker log has `up` then `down` with `-p megoo-meg-1-test-…`, and `<cache>/services` holds no `.json`.
2. Run: `go test ./internal/services/ ./internal/fakeagent/ ./internal/jobs/ -run 'TestPromptSection|Run|Services|Section'` → fails.
3. Implement:
   - `Manager.Executable func() (string, error)` (default `os.Executable` in `New`).
   - `jobs/services.go`: `func (m *Manager) servicesDir() string { return filepath.Join(m.cacheRoot, "services") }` and `func (m *Manager) servicesEnv(logf io.Writer) []string` → `PATH=<dir of Executable()><os.PathListSeparator><os.Getenv("PATH")>` (skipped with a log line if `Executable` fails) and `MEGOO_SERVICES_DIR=<servicesDir>`.
   - `drive`: just before `spec.Env = append(spec.Env, secretEnv(rs.Secrets)...)`, `spec.Env = append(spec.Env, m.servicesEnv(logf)...)` (secrets stay last and cannot name `PATH` or `MEGOO*`; Go keeps the last of duplicate keys, case-insensitively on Windows). Before `r.content(sess.prompt, …)`: `text := sess.prompt`; if `kind == policy.Workspace && rs.Draft == nil`, append `services.PromptSection(wt)` (error → `runner: services: <err>` in the run log, no section); pass `text` to `r.content`.
4. Run again → pass; `go test ./...`.

Commit: `feat(runner): runs are told about the test services and can call the command (MC-52)`.

### Step 9. feat(runner): remove a worktree's services when its run ends, and sweep hourly (MC-52)

Files: `runner/internal/jobs/services.go`, `services_test.go`, `manager.go`, `runner/cmd/run.go` (changed).

1. Tests first, in `jobs/services_test.go` (fake docker on `PATH`; a record written by the test into `<cache>/services/<p>.json` before `startRun`, with `Worktree: services.Canonical(e.worktree("MEG-1"))`, `Project: services.ProjectName(<that>, "test")`, `PID: os.Getpid()` (alive, so only layer 2 can remove it), no Compose files):
   - `TestRunEndRemovesTheWorktreesServices`: scenario `[{"say":"done"}]` → when `finished("run-1")` arrives, the fake docker log already has `compose -p <p> down …` and the record is gone. A second record for another worktree, also with a live PID, is still there.
   - `TestCancelledRunRemovesTheWorktreesServices`: scenario `[{"sleep_ms":30000}]`, wait for the run to start (`waitUpdate` after a first `say`), send `protocol.RunCancel` like `TestCancelStopsAgent` → `finished` is `cancelled`, then the record is gone.
   - `TestRemovalFailureIsLoggedAndKept`: `FAKEDOCKER_FAIL=down,rm`, `FAKEDOCKER_LEFTOVER=1` → the run still finishes `completed`, the record stays, `<cache>/logs/run-1.log` contains `runner: services:`, and `m.Log` (a `bytes.Buffer` set via tweak, guarded by a mutex wrapper) contains the project.
   - `TestServeSweepsDeadServices`: a record with a dead PID (from a finished `exec.Command("git","--version")`) written before `newEnvWithCache` → removed shortly after Serve starts (poll up to 10 s).
   - `TestDraftRunsSkipServices`: no removal call for a draft run (use the existing draft test setup in `drafts_test.go`).
2. Run: `go test ./internal/jobs/ -run 'TestRunEnd|TestCancelledRun|TestRemovalFailure|TestServeSweeps|TestDraftRunsSkip'` → fails.
3. Implement:
   - `Manager.Log io.Writer` (default `io.Discard` in `New`); in `cmd/run.go` `runConnection`, `mgr.Log = out`.
   - `const servicesWait = 2 * time.Minute`, `const servicesSweepEvery = time.Hour`.
   - `func (m *Manager) removeServices(wt string, logf io.Writer)`: `ctx, cancel := context.WithTimeout(context.Background(), servicesWait)`; `services.CleanWorktree(ctx, m.servicesDir(), wt)`; an error → `runner: services: <err>` to `logf` and `services: <err>` to `m.Log`.
   - In `drive`, right after the worktree/cron block (after the `if rs.Cron != nil … else …` that sets `wt`), `if rs.Draft == nil { defer m.removeServices(wt, logf) }`. It is registered before the adapter's `reap` defer and the git-after defer, so it runs after the agent is gone, and before `execute` sends `run_finished`.
   - `func (m *Manager) sweepServices(ctx context.Context)`: `services.Sweep` now and every `servicesSweepEvery` until `ctx` ends, errors to `m.Log`. Start it in `Serve` next to `go m.sweepDrafts(ctx)`.
4. Run again → pass; `go test ./...` and `go vet ./...`.

Commit: `feat(runner): remove a worktree's services when its run ends, and sweep hourly (MC-52)`.

### Step 10. test(runner): one real Docker check of services run in CI (MC-52)

Files: `runner/internal/services/docker_test.go`, `runner/internal/services/testdata/real/megoocolab.toml`, `testdata/real/compose.yml`, `testdata/real/web/Dockerfile` (new); `helper_test.go` (changed); `.github/workflows/ci.yml` (changed).

- `testdata/real/megoocolab.toml`: `[services.web]`, `compose = ["compose.yml"]`, `ports = ["WEB_PORT"]`.
- `compose.yml`: service `web`, `build: ./web`, `ports: ["127.0.0.1:${WEB_PORT:?}:80"]`, a named volume `data:/data`, healthcheck `["CMD", "wget", "-q", "-O-", "http://localhost/"]` (interval 1s, retries 30).
- `web/Dockerfile`: `FROM nginx:1.27-alpine`.
- `helper_test.go`: new mode `get:NAME` → HTTP GET `http://127.0.0.1:<$NAME>/`, exit 0 on 200, else 1.

1. Test `TestRealDocker`: `t.Skip` unless `MEGOO_DOCKER_TESTS=1`. Copy `testdata/real` to a temp dir, `Run` with `Set: "web"`, `Command: []string{os.Args[0]}`, `SERVICES_TEST_HELPER=get:WEB_PORT` → 0. Then, with the real `docker`: `ps -aq --filter label=com.docker.compose.project=<p>`, `volume ls -q --filter …`, `network ls -q --filter …` are all empty, `image inspect <p>-web` fails, and `MEGOO_SERVICES_DIR` holds no `.json`.
2. Run locally with Docker: `MEGOO_DOCKER_TESTS=1 go test ./internal/services/ -run TestRealDocker -count=1 -v` → passes (without the variable it is skipped). Before the helper mode exists it fails.
3. CI: in the `runner` job after `go test ./...`, add
   ```yaml
         # one real Docker check of `services run`; Docker is only on the Linux runners
         - if: runner.os == 'Linux'
           run: go test ./internal/services -run TestRealDocker -count=1 -v
           env:
             MEGOO_DOCKER_TESTS: "1"
   ```
4. `go test ./...` passes (skipped locally without the variable).

Commit: `test(runner): one real Docker check of services run in CI (MC-52)`.

### Step 11. feat: this repository declares its test services in megoocolab.toml (MC-52)

Files: `megoocolab.toml`, `tools/test-services/docker-compose.yml`, `tools/test-services/initdb/01-migrate.sql` (new); `runner/internal/services/repo_file_test.go` (new). The file contents are in "Step 11 files" below.

1. Test first `TestRepositoryFileLoads`: `Load("../../../megoocolab.toml")` succeeds; sets are `e2e`, `migrate`, `test`; `e2e` ports are `HTTP_PORT`, `HTTPS_PORT`; `Vars` for each set with fixed ports and an empty lookup succeeds (every `${…}` resolves); `PromptSection` of the repository root contains all three names.
2. Run: `go test ./internal/services/ -run TestRepositoryFileLoads` → fails (no file).
3. Add the three files.
4. Run again → pass. Then by hand, with Docker, from `backend/`: `megoocolab-runner services run test -- uv run pytest -q -n auto` (built from this branch: `go build -o /tmp/mr/megoocolab-runner ./runner` from the repository root and call that path) → green, and `docker ps -a --filter name=megoo-` empty afterwards.

Commit: `feat: this repository declares its test services in megoocolab.toml (MC-52)`.

### Step 12. docs: checks run through megoocolab-runner services run (MC-52)

Files: `AGENTS.md`, `README.md`, `runner/README.md`. Exact replacements are in "Step 12 text" below.

1. `AGENTS.md` "Checks": Backend, Migrations and Browser tests bullets replaced; "Safety" Docker bullet replaced.
2. `README.md`: the "### End-to-end test" block (the `cp deploy/.env.example .superpowers/e2e.env` line and the two `docker compose -p megoo-e2e …` lines) becomes the `services run e2e` form; the backend test lines say the tests can also run on their own services with `services run test`. Every later section that says "the same stack as above" stays true.
3. `runner/README.md`: a new "## Test services" section before "## What the runner does and does not do".
4. Check: `grep -n 'megoo-e2e\|e2e.env\|megoo_migrate\|second pytest' AGENTS.md README.md` finds nothing (the `megoo_migrate` scratch database lives only inside the `migrate` set now); `go test ./...` in `runner/` still passes.

Commit: `docs: checks run through megoocolab-runner services run (MC-52)`.

### Step 13. Verify by hand: two worktrees at once, migrations, browser tests, cleanup

No code. Build the runner from this branch (`go build -o <tmp>/megoocolab-runner ./runner`, put `<tmp>` first on `PATH`). Then:

1. Two worktrees of this repository on this branch, at the same time, from `backend/`: `megoocolab-runner services run test -- uv run pytest -q -n auto` → both green (the known flaky tests in the project memory aside; rerun them alone if they fail).
2. From `backend/`: `megoocolab-runner services run migrate -- bash scripts/makemigration.sh "probe"` creates a migration (delete it afterwards, do not commit it), and `megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"` passes.
3. With `megoocolab-dev-caddy-1` left running: from `frontend/`, `megoocolab-runner services run e2e -- npx playwright test --reporter=line` in one worktree while the other runs `megoocolab-runner services run e2e -- npx playwright test e2e/kb.spec.ts --reporter=line` → both pass.
4. Start `megoocolab-runner services run test -- sleep 600`, `kill -9` the runner process → containers stay; the next `services run test` in that worktree removes them first; `megoocolab-runner services clean` removes any others.
5. `docker ps -a --filter name=megoo-`, `docker volume ls --filter label=com.docker.compose.project` and `docker network ls` show nothing left from `megoo-…-<8 hex>` projects; `megoocolab-*` containers are untouched.

Record the results with `record_tests`.

## Step 11 files

`megoocolab.toml` (repository root):

```toml
# Services the checks need. Run a check as `megoocolab-runner services run <name> -- <command>`: the runner starts
# this worktree's own containers on free ports, runs the command with the variables below, then removes them.
# Every value here is for throwaway local containers; none of them is a real secret.

[services.test]
description = "PostgreSQL, Meilisearch and Valkey for the backend tests (pytest)"
compose = ["tools/test-services/docker-compose.yml"]
ports = ["DB_PORT", "MEILI_PORT", "VALKEY_PORT"]

[services.test.env]
TEST_DATABASE_URL = "postgresql+asyncpg://megoo:megoo@localhost:${DB_PORT}/megoo_test"
MEILI_URL = "http://localhost:${MEILI_PORT}"
MEILI_MASTER_KEY = "megoo-test-meili-key"
VALKEY_URL = "valkey://localhost:${VALKEY_PORT}/0"
VALKEY_PASSWORD = "megoo-dev-valkey"

[services.migrate]
description = "a scratch PostgreSQL database (megoo_migrate) to generate and check Alembic migrations"
compose = ["tools/test-services/docker-compose.yml"]
ports = ["DB_PORT", "MEILI_PORT", "VALKEY_PORT"]

[services.migrate.env]
DATABASE_URL = "postgresql+asyncpg://megoo:megoo@localhost:${DB_PORT}/megoo_migrate"
DEV_DATABASE_URL = "postgresql+asyncpg://megoo:megoo@localhost:${DB_PORT}/megoo_migrate"
SECRET_KEY = "dev"
MEILI_MASTER_KEY = "megoo-test-meili-key"
VALKEY_PASSWORD = "megoo-dev-valkey"

[services.e2e]
description = "the whole app built from this worktree, for the browser tests (Playwright)"
compose = ["deploy/docker-compose.yml", "deploy/docker-compose.build.yml"]
ports = ["HTTP_PORT", "HTTPS_PORT"]

[services.e2e.env]
# each build gets its own tag, so two worktrees never start each other's images
MEGOO_VERSION = "${MEGOO_SERVICES_PROJECT}"
PUBLIC_URL = "http://localhost:${HTTP_PORT}"
E2E_BASE_URL = "http://localhost:${HTTP_PORT}"
POSTGRES_PASSWORD = "megoo-e2e-db"
SECRET_KEY = "megoo-e2e-secret-key-0123456789abcdef"
MEILI_MASTER_KEY = "megoo-e2e-meili-key"
VALKEY_PASSWORD = "megoo-e2e-valkey"
CLIENT_IP_HEADER = "X-Real-IP"
AI_FAKE = "true"
MEMORY_EXTRACT_DELAY_SECONDS = "2"
```

`tools/test-services/docker-compose.yml`:

```yaml
# The databases the checks use, started per worktree by `megoocolab-runner services run test|migrate` (see
# megoocolab.toml). Data lives in memory and goes away with the containers. Not part of a release.
services:
  db:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: megoo
      POSTGRES_PASSWORD: megoo
      POSTGRES_DB: megoo_test
    ports: ["127.0.0.1:${DB_PORT:?run through megoocolab-runner services run}:5432"]
    tmpfs: [/var/lib/postgresql/data]
    volumes:
      - ./initdb:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U megoo -d megoo_test"]
      interval: 2s
      timeout: 3s
      retries: 30

  meilisearch:
    image: getmeili/meilisearch:v1.55.0
    environment:
      MEILI_MASTER_KEY: ${MEILI_MASTER_KEY:?run through megoocolab-runner services run}
      MEILI_NO_ANALYTICS: "true"
    ports: ["127.0.0.1:${MEILI_PORT:?run through megoocolab-runner services run}:7700"]
    tmpfs: [/meili_data]
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:7700/health"]
      interval: 2s
      timeout: 3s
      retries: 30

  valkey:
    image: valkey/valkey:8.1.3
    command: ["valkey-server", "--requirepass", "${VALKEY_PASSWORD:?run through megoocolab-runner services run}", "--save", "", "--appendonly", "no"]
    environment:
      VALKEY_PASSWORD: ${VALKEY_PASSWORD}
    ports: ["127.0.0.1:${VALKEY_PORT:?run through megoocolab-runner services run}:6379"]
    healthcheck:
      test: ["CMD-SHELL", "valkey-cli -a \"$$VALKEY_PASSWORD\" --no-auth-warning ping | grep -q PONG"]
      interval: 2s
      timeout: 3s
      retries: 30
```

`tools/test-services/initdb/01-migrate.sql`:

```sql
-- the scratch database for generating and checking migrations (services set "migrate")
CREATE DATABASE megoo_migrate;
```

## Step 12 text

`AGENTS.md`, "Checks", replace the Backend, Migrations and Browser tests bullets with:

```markdown
- **Services for checks**: the backend tests, migrations and browser tests need containers. Run them only through
  `megoocolab-runner services run <set> -- <command>` (sets in `megoocolab.toml`): it starts this worktree's own
  containers on free ports, gives the command their addresses, and removes them when the command ends, pass or fail.
  Two worktrees can run checks at the same time.
- **Backend** (`backend/`): `megoocolab-runner services run test -- uv run pytest` (add `-q -n auto` for the whole
  suite).
- **Migrations** (`backend/`): generate them on the `migrate` set's scratch database, never the dev database `megoo`:

  ```bash
  megoocolab-runner services run migrate -- bash scripts/makemigration.sh "<message>"
  ```

  Give every new foreign key and unique constraint an explicit name, and check that the migration goes down and up
  again. The database is new for each command, so do it in one:
  `megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"`.
- **Runner** (`runner/`): `go test ./...`.
- **Browser tests** (Playwright, `frontend/e2e/`): run them on a freshly built stack before merging a change to the
  app. `BUILDX_BAKE_ENTITLEMENTS_FS=0` is needed on Windows: without it, recent Docker versions stop the build to
  ask for permission to read `backend\Dockerfile`. From `frontend/`:

  ```bash
  megoocolab-runner services run e2e -- npx playwright test --reporter=line
  ```

  Each command builds and starts a fresh stack, so specs that need a fresh stack just run again.
```

(The "Runner" bullet stays where it was; the screenshot sentence "A spec written only to take screenshots …" stays after the browser tests block.)

`AGENTS.md`, "Safety", replace the Docker bullet with:

```markdown
- Docker: start and stop containers for checks only through `megoocolab-runner services run`, and otherwise touch
  only the dev containers (`megoocolab-dev-*`). Never stop, remove or change `cloudflared` or any other
  `megoocolab-*` container: those run the owner's real instance.
```

…and drop the sentence about `.superpowers/e2e.env` from the next bullet (keep "Never read files that hold credentials or secrets (`.env` files, tokens, keys).").

`README.md`, "### End-to-end test": replace the `cp deploy/.env.example .superpowers/e2e.env …` line and the `docker compose … up` / `… down -v` lines with

```bash
cd frontend && npx playwright install chromium
megoocolab-runner services run e2e -- npx playwright test
```

and one sentence: "`services run e2e` (set in `megoocolab.toml`) builds the stack from this checkout on free ports, passes `E2E_BASE_URL`, and removes the stack, its volumes and its images when the tests end. Every run starts on a fresh stack." Single-spec examples later in the file become `megoocolab-runner services run e2e -- npx playwright test e2e/<spec>.ts` (run from `frontend/`). In the backend lines, add: "or, on containers of its own (no dev stack needed): `megoocolab-runner services run test -- uv run pytest -n auto`."

`runner/README.md`, new section "## Test services" before "## What the runner does and does not do": what `megoocolab.toml` is (the design's example file), the keys (`compose` required, relative to the file; `ports`; `env` with `${NAME}` for a port, `MEGOO_SERVICES_PROJECT` or a variable already in the environment; `description`, one line, at most 200 characters), the name rules, the two commands, the exit codes (the command's own; 125 when the runner could not start or remove the services, or the set is already running in this worktree), where records and logs live (`<user cache dir>/megoocolab/services`, or `MEGOO_SERVICES_DIR`), the three layers of removal (when the command ends; when a run ends; at runner start, every hour and before each `services run`), that writable runs in a worktree with the file get a "Test services" section in their prompt, and that the runner only removes Compose projects it recorded, named `megoo-…-<8 hex>`.

## Final verification

From `runner/`:

```bash
go vet ./...
go test ./...
MEGOO_DOCKER_TESTS=1 go test ./internal/services -run TestRealDocker -count=1 -v   # needs Docker
go run . services --help
```

From the repository root: `python tools/release/versions.py check` (no version file changed). Then step 13's by-hand checks, ending with no `megoo-…-<8 hex>` container, volume or network left (`docker ps -a --filter name=megoo-`).

## Requirement coverage

| Design requirement | Step |
|---|---|
| `megoocolab.toml` format, names, validation, one-line errors | 2, 3 |
| Project name with path hash; `MEGOO_SERVICES_PROJECT`; `${NAME}` expansion; free ports | 3, 5 |
| Records and env file in the cache folder, never the worktree | 4, 5 |
| `up -d --build --wait` with own env file; port retry ×3; logs on failure | 5 |
| Command run in its folder, input/output passed, signals forwarded, exit code; 125 cases | 6, 7 |
| Remove containers, volumes, networks, built images (pulled stay) | 4 |
| One check per set per worktree; refused at once | 4, 6 |
| `services clean` | 7 |
| Prompt section for writable runs only; read-only and no-file get nothing | 8 |
| Runner folder first on `PATH`; `MEGOO_SERVICES_DIR`; secrets cannot override | 8 |
| Layer 2 at run end (success, failure, cancel), 2 minutes, logged | 9 |
| Layer 3 at start and hourly; before every `services run`; logs older than 7 days | 4, 6, 9 |
| Safety: only recorded `megoo-…-<8 hex>` projects; test proves it | 4 |
| Docker missing / not running | 5, 6 |
| Real Docker test in CI on Linux | 10 |
| This repository: `megoocolab.toml`, `tools/test-services/`, docs | 11, 12 |
| By-hand checks | 13 |
