# MC-2 implementation plan: a runner service that comes back, and says why when it doesn't

## Goal
After `megoocolab-runner service install` the runner starts at every logon (Windows), comes back after a crash, and always leaves a timestamped trace in `runner.log`. `service status` on Windows says when autostart is broken. Linux re-install in the `failed` state and the macOS exit-78 loop are fixed too.

## Architecture
In service mode, `run` opens the log first and writes a start line and its final error there. On Windows, `run --background` takes one of three roles, chosen from `MEGOOCOLAB_RUNNER_HIDDEN`. The launcher is started by the Run key and always relaunches hidden. The supervisor owns the pid file and restarts the worker with backoff. The worker is today's runner. Shared `service install/start` code checks the login first; install then registers and starts the runner. Exit 78 now also covers "not logged in", and on macOS in service mode it becomes 0, so a launchd `KeepAlive {SuccessfulExit=false}` plist stops instead of looping.

All code is in the Go module `runner/` (package `cmd`). CI runs `go test ./...` and `go vet ./...` in `runner/` on Linux, Windows and macOS. Commit style: `fix(runner): … (MC-2)`.

## File map
| File | Change |
|---|---|
| `runner/cmd/runlog.go` (new) | `tsWriter` (timestamp prefix per line), `logPath`, `openServiceLog` (runner.log or a temp fallback). |
| `runner/cmd/runlog_test.go` (new) | Tests for the above. |
| `runner/cmd/service.go` | `openRunLog` returns `*os.File` and uses `logPath`. The shared `serviceInstall`/`serviceStart` flow. `launchdUserPlist` and the `LaunchdConfig` option. |
| `runner/cmd/login.go` | `errNotLoggedIn`, `loadConfig` (a var, so tests can replace it), `loadLogin()`. |
| `runner/cmd/root.go` | `quietError`, `exitCode(err, goos, interactive)`; `Execute` uses both. |
| `runner/cmd/run.go` | Logging-first `runService`/`runServiceAt`, role dispatch. |
| `runner/cmd/supervise.go` (new) | Platform-independent `supervisor` loop with injected deps. |
| `runner/cmd/supervise_test.go` (new) | Fake worker and clock tests. |
| `runner/cmd/service_proc.go` | `bgRole`, `backgroundRole`, `runValueExe`, `startupDisabled`, `autostartLines`, `fileExists`. Removes `shouldRelaunchHidden`. |
| `runner/cmd/service_windows.go` | `hiddenCmd`, `spawnSupervisor`, `runWorkerProcess`, `otherRunnerPID`. Install re-enables StartupApproved, Status adds the autostart lines, the Start failure message points at the log. Removes the console-visibility code. |
| `runner/cmd/relaunch_other.go` → `runner/cmd/background_other.go` (git mv) | Non-Windows stubs for the three Windows functions. |
| `runner/cmd/service_other.go` | `libManager.Install` uninstalls whenever the status isn't "not installed". |
| `runner/cmd/service_other_test.go` (new, `//go:build !windows`) | Fake kardianos service test. |
| `runner/cmd/service_test.go`, `runner/cmd/root_test.go` | Updated and extended tests. |
| `runner/README.md`, `docs/install.md` | Docs. |

## Shared contracts (same names in every step)

```go
// runlog.go
type tsWriter struct {
	mu      sync.Mutex
	w       io.Writer
	now     func() time.Time
	midLine bool // the last write did not end with '\n'
}
func newTSWriter(w io.Writer, now func() time.Time) *tsWriter
// Write writes p, putting now().Format(time.RFC3339) + " " before each line start. It returns len(p), nil
// unless the underlying write fails.
func (t *tsWriter) Write(p []byte) (int, error)
func logPath(cacheRoot string) string // <cacheRoot>/logs/runner.log
const fallbackLogName = "megoocolab-runner-start.log"
// openServiceLog opens runner.log under root. If root is "" or that fails, it opens
// <tempDir>/megoocolab-runner-start.log for appending. If both fail it returns (nil, "").
func openServiceLog(root, tempDir string) (*os.File, string)

// login.go
var errNotLoggedIn = errors.New("not logged in")
var loadConfig = config.Load
// loadLogin returns fmt.Errorf("%w (%v); run: megoocolab-runner login --url URL --token TOKEN", errNotLoggedIn, err)
func loadLogin() (config.Config, error)

// root.go
type quietError struct{ err error }   // already written to runner.log; Execute does not print it
func (q quietError) Error() string { return q.err.Error() }
func (q quietError) Unwrap() error { return q.err }
func exitCode(err error, goos string, interactive bool) int

// service_proc.go
type bgRole int
const (
	roleSingle     bgRole = iota // Linux, macOS, or no --background: one process, today's behaviour
	roleLauncher                 // Windows, marker unset: started by the Run key
	roleSupervisor               // Windows, marker "1": also what `service start` spawns
	roleWorker                   // Windows, marker "worker"
)
const workerMarker = "worker"
func backgroundRole(goos, marker string) bgRole
func runValueExe(value string) (string, bool)
func startupDisabled(b []byte) bool
func autostartLines(value string, exists func(string) bool, disabled bool) []string
func fileExists(path string) bool

// supervise.go
const (
	restartMin   = 5 * time.Second
	restartMax   = 120 * time.Second
	restartReset = 5 * time.Minute
)
type supervisor struct {
	log           io.Writer
	otherRunning  func() (int, bool)       // a live runner named by the pid file
	claim         func() (func(), error)   // beginBackground(root)
	runWorker     func() (int, error)      // start the worker, wait, return its exit status
	stopRequested func() bool              // the stop file exists
	now           func() time.Time
	sleep         func(time.Duration)
}
func (s supervisor) run() error

// platform (service_windows.go / background_other.go)
func spawnSupervisor(exe string) error
func runWorkerProcess(exe string, logf *os.File) func() (int, error)
func otherRunnerPID(root, exe string) (int, bool)

// service.go
func serviceInstall(m serviceManager, out io.Writer) error
func serviceStart(m serviceManager, out io.Writer) error
```

### Supervisor algorithm (step 3)
```go
func (s supervisor) run() error {
	if pid, ok := s.otherRunning(); ok {
		fmt.Fprintf(s.log, "another runner is already running (pid %d); exiting\n", pid)
		return nil
	}
	release, err := s.claim()
	if err != nil {
		return fmt.Errorf("cannot write the pid file: %w", err)
	}
	defer release()
	delay := restartMin
	for {
		if s.stopRequested() {
			fmt.Fprintln(s.log, "stop requested; not starting the runner")
			return nil
		}
		started := s.now()
		code, err := s.runWorker()
		if err != nil {
			return fmt.Errorf("cannot start the runner: %w", err)
		}
		switch code {
		case 0:
			fmt.Fprintln(s.log, "runner stopped")
			return nil
		case exitStoppedByServer:
			fmt.Fprintf(s.log, "runner exited with status %d (run `megoocolab-runner login`, then `service start`); not restarting\n", code)
			return nil
		}
		if s.now().Sub(started) >= restartReset {
			delay = restartMin
		}
		fmt.Fprintf(s.log, "runner exited with status %d; restarting in %s\n", code, delay)
		if !s.wait(delay) {
			fmt.Fprintln(s.log, "stop requested; not restarting the runner")
			return nil
		}
		delay = min(delay*2, restartMax)
	}
}

// wait sleeps d in steps of at most one second and returns false as soon as a stop is requested.
func (s supervisor) wait(d time.Duration) bool {
	for left := d; left > 0; left -= time.Second {
		if s.stopRequested() {
			return false
		}
		s.sleep(min(time.Second, left))
	}
	return true
}
```
Delays in a crash loop: 5s, 10s, 20s, 40s, 80s, 120s, 120s… Once a worker stays up 5 minutes or more, the next delay is 5s again.

### run.go after step 4/5
```go
RunE: func(cmd *cobra.Command, _ []string) error {
	if !background && service.Interactive() {
		cfg, err := loadLogin()
		if err != nil {
			return err
		}
		ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		return runConnection(ctx, cmd.OutOrStdout(), cfg, version)
	}
	role := roleSingle
	if background {
		role = backgroundRole(runtime.GOOS, os.Getenv(relaunchEnv))
	}
	return runService(cmd.Context(), role, version)
},

func runService(ctx context.Context, role bgRole, version string) error {
	root, rootErr := cacheRoot()
	return runServiceAt(ctx, role, version, root, rootErr, os.TempDir())
}

func runServiceAt(ctx context.Context, role bgRole, version, root string, rootErr error, tempDir string) error {
	var logf *os.File
	if role == roleWorker {
		logf = os.Stderr // the supervisor pointed stdout and stderr at runner.log
	} else {
		logRoot := root
		if rootErr != nil {
			logRoot = ""
		}
		logf, _ = openServiceLog(logRoot, tempDir)
		if logf != nil {
			defer logf.Close()
		}
	}
	var log io.Writer = io.Discard
	if logf != nil {
		log = newTSWriter(logf, time.Now)
	}
	fmt.Fprintf(log, "starting megoocolab-runner %s (pid %d)\n", version, os.Getpid())
	err := serveRole(ctx, role, version, root, rootErr, log, logf)
	if err != nil {
		fmt.Fprintf(log, "error: %v\n", err)
		if role == roleWorker {
			return quietError{err}
		}
	}
	return err
}
```
`serveRole`:
- `rootErr != nil` → return it.
- `roleLauncher` → `exe, err := os.Executable()`, then `spawnSupervisor(exe)`. Wrap a failure as `cannot start the hidden runner: %w`.
- `roleSupervisor` → build `supervisor{log, otherRunning: func() (int, bool) { return otherRunnerPID(root, exe) }, claim: func() (func(), error) { return beginBackground(root) }, runWorker: runWorkerProcess(exe, logf), stopRequested: func() bool { return fileExists(stopPath(root)) }, now: time.Now, sleep: time.Sleep}` and return `.run()`.
- `roleWorker` and `roleSingle` → `cfg, err := loadLogin()`; `ctx` gets `signal.NotifyContext(os.Interrupt, syscall.SIGTERM)` plus a cancel; `go watchStopFile(ctx, stopPath(root), time.Second, cancel)`. Only `roleSingle` also calls `beginBackground(root)` (pid file + stale stop file cleanup, as today). Then `runConnection(ctx, log, cfg, version)`.

### macOS plist (step 9)
`launchdUserPlist` is kardianos/service v1.3.0's `launchdConfig` template from `service_darwin.go`, copied verbatim with one change. The `KeepAlive`/`RunAtLoad` pair becomes:
```xml
    <key>KeepAlive</key>
    <dict>
      <key>SuccessfulExit</key>
      <false/>
    </dict>
    <key>RunAtLoad</key>
    <true/>
```
Copy the real template from `$(go env GOMODCACHE)/github.com/kardianos/service@v1.3.0/service_darwin.go` (`var launchdConfig = ...`). Keep every other line, and every field and function it uses (`.Name`, `.Path`, `.Config.Arguments`, `.EnvVars`, `bool`, `html`, StandardOut/ErrorPath, SessionCreate…), exactly as they are. Then `serviceConfig` sets `Option["LaunchdConfig"] = launchdUserPlist`.

## Steps

### 1. Timestamped service log with a fallback file
See step detail.

### 2. Not-logged-in is exit 78; macOS service mode maps 78 to 0; quiet errors
See step detail.

### 3. Supervisor loop (platform independent)
See step detail.

### 4. `run` in service mode opens the log first and logs start and final error
See step detail.

### 5. Windows: launcher / supervisor / worker roles; drop the console-visibility check
See step detail.

### 6. Shared `service install` / `service start` flow
See step detail.

### 7. Windows: install re-enables the startup entry; status explains broken autostart
See step detail.

### 8. Linux: re-install works when the unit is failed
See step detail.

### 9. macOS: LaunchAgent restarts after crashes only
See step detail.

### 10. Docs: runner README and install guide
See step detail.

(The full detail of each step is in the `steps` array. It is the same text the build agent receives.)

## Final verification
```sh
cd runner
gofmt -l .                       # prints nothing
go vet ./...
go test ./...
GOOS=windows go vet ./...        # Windows-only files compile
GOOS=darwin go vet ./...
GOOS=windows go test -c -o /dev/null ./cmd/
```
CI runs `go test ./...` on ubuntu, windows and macos. All three must be green.

Manual checks on the reporter's Windows 11 machine (from the design):
1. Before updating, note: `service status`, the Run value and whether its file exists, the Startup apps state, and the default terminal.
2. After updating, run `service install`. It prints the status with `running (pid N)` and the `autostart:` line. Restart and sign in. `service status` says `running`, and `runner.log` has timestamped `starting megoocolab-runner …` lines from the logon.
3. Repeat with "Windows Console Host" and with "Windows Terminal" as the default terminal. Each time no window stays open and the runner is running.
4. End the worker `megoocolab-runner.exe` (the child) in Task Manager. The log shows `restarting in 5s` and the runner is back.
5. Disable the entry in Startup apps. `service status` warns. `service install` clears the warning.
6. Rename `runner.json` and run `service install`. It refuses with `not logged in`.
