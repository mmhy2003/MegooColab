package jobs

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
	"github.com/mmhy2003/megoocolab/runner/internal/services"
	"github.com/mmhy2003/megoocolab/runner/internal/testutil"
)

// commitFiles writes files (paths relative to repo, with / separators) and
// commits them, so a new worktree has them.
func commitFiles(t *testing.T, repo string, files map[string]string) {
	t.Helper()
	for name, body := range files {
		p := filepath.Join(repo, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	for _, args := range [][]string{
		{"add", "-A"},
		{"-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "files"},
	} {
		if out, err := exec.Command("git", append([]string{"-C", repo}, args...)...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
}

// servicesFiles is a megoocolab.toml with one set, `test`, and its Compose file.
var servicesFiles = map[string]string{
	"megoocolab.toml": "[services.test]\ncompose = [\"svc/compose.yml\"]\nports = [\"DB_PORT\"]\n",
	"svc/compose.yml": "services: {}\n",
}

func TestWritableRunGetsTheServicesSection(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"done"}]`, 1, t.TempDir())
	commitFiles(t, e.repo, servicesFiles)
	e.startRun("run-1", "MEG-1", "workspace")
	if f := e.finished("run-1"); f.Outcome != "completed" {
		t.Fatalf("finished = %+v", f)
	}
	r := e.readReport()
	if len(r.Prompts) == 0 || !strings.Contains(r.Prompts[0], "## Test services") || !strings.Contains(r.Prompts[0], "`test`") {
		t.Fatalf("prompts = %q", r.Prompts)
	}
}

func TestReadOnlyRunAndRunsWithoutTheFileGetNoSection(t *testing.T) {
	for _, tc := range []struct {
		name, policy string
		files        bool
	}{
		{"read only with the file", "read_only", true},
		{"workspace without the file", "workspace", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			e := newEnvWithCache(t, `[{"say":"done"}]`, 1, t.TempDir())
			if tc.files {
				commitFiles(t, e.repo, servicesFiles)
			}
			e.startRun("run-1", "MEG-1", tc.policy)
			if f := e.finished("run-1"); f.Outcome != "completed" {
				t.Fatalf("finished = %+v", f)
			}
			r := e.readReport()
			if len(r.Prompts) == 0 {
				t.Fatal("no prompt")
			}
			if strings.Contains(r.Prompts[0], "## Test services") {
				t.Fatalf("prompt = %q", r.Prompts[0])
			}
		})
	}
}

func TestRunCanCallServicesRunByName(t *testing.T) {
	dockerLog := useFakeDocker(t)
	runner := testutil.BuildRunner(t)
	cache := t.TempDir()
	e := newEnvWithCache(t,
		`[{"run":{"args":["megoocolab-runner","services","run","test","--","git","--version"]}}]`, 1, cache,
		func(m *Manager) { m.Executable = func() (string, error) { return runner, nil } })
	commitFiles(t, e.repo, servicesFiles)
	e.startRun("run-1", "MEG-1", "workspace")
	if f := e.finished("run-1"); f.Outcome != "completed" {
		t.Fatalf("finished = %+v", f)
	}
	r := e.readReport()
	if len(r.Steps) != 1 || r.Steps[0].Type != "run" || r.Steps[0].Outcome != "exit:0" {
		t.Fatalf("steps = %+v", r.Steps)
	}

	var verbs []string
	b, err := os.ReadFile(dockerLog)
	if err != nil {
		t.Fatalf("docker log: %v", err)
	}
	sc := bufio.NewScanner(strings.NewReader(string(b)))
	for sc.Scan() {
		var call struct {
			Args []string `json:"args"`
		}
		if err := json.Unmarshal(sc.Bytes(), &call); err != nil {
			t.Fatal(err)
		}
		if len(call.Args) < 3 || call.Args[0] != "compose" {
			continue
		}
		i := slices.Index(call.Args, "-p")
		if i < 0 || i+1 >= len(call.Args) || !strings.HasPrefix(call.Args[i+1], "megoo-meg-1-test-") {
			t.Fatalf("compose call without our project: %q", call.Args)
		}
		for _, verb := range []string{"up", "down"} {
			if slices.Contains(call.Args, verb) {
				verbs = append(verbs, verb)
			}
		}
	}
	if strings.Join(verbs, " ") != "up down" {
		t.Fatalf("compose verbs = %q\n%s", verbs, b)
	}
	left, _ := filepath.Glob(filepath.Join(cache, "services", "*.json"))
	if len(left) != 0 {
		t.Fatalf("records left: %v", left)
	}
}

// useFakeDocker puts the fake docker first on PATH with its knobs cleared and
// returns the file it logs its calls to.
func useFakeDocker(t *testing.T) string {
	t.Helper()
	t.Setenv("PATH", testutil.BuildFakeDocker(t)+string(os.PathListSeparator)+os.Getenv("PATH"))
	dockerLog := filepath.Join(t.TempDir(), "docker.log")
	t.Setenv("FAKEDOCKER_LOG", dockerLog)
	for _, name := range []string{"FAKEDOCKER_FAIL", "FAKEDOCKER_LEFTOVER", "FAKEDOCKER_SHOW",
		"FAKEDOCKER_PORT_TAKEN", "FAKEDOCKER_CONFIG", "FAKEDOCKER_UP_SLEEP_MS", "MEGOO_SERVICES_DIR"} {
		t.Setenv(name, "")
	}
	return dockerLog
}

// writeRecord saves a record of set `test` in worktree, started by pid, into
// the cache's services folder, and returns its project.
func writeRecord(t *testing.T, cache, worktree string, pid int) string {
	t.Helper()
	dir := filepath.Join(cache, "services")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	wt := services.Canonical(worktree)
	p := services.ProjectName(wt, "test")
	if err := services.Save(dir, services.Record{Project: p, Worktree: wt, Set: "test", PID: pid, Started: time.Now()}); err != nil {
		t.Fatal(err)
	}
	return p
}

func recordExists(cache, project string) bool {
	_, err := os.Stat(filepath.Join(cache, "services", project+".json"))
	return err == nil
}

// dockerCalls returns the argument lists the fake docker logged.
func dockerCalls(t *testing.T, dockerLog string) [][]string {
	t.Helper()
	b, err := os.ReadFile(dockerLog)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	var calls [][]string
	sc := bufio.NewScanner(strings.NewReader(string(b)))
	for sc.Scan() {
		var call struct {
			Args []string `json:"args"`
		}
		if err := json.Unmarshal(sc.Bytes(), &call); err != nil {
			t.Fatal(err)
		}
		calls = append(calls, call.Args)
	}
	return calls
}

func downCalled(t *testing.T, dockerLog, project string) bool {
	for _, args := range dockerCalls(t, dockerLog) {
		if len(args) > 3 && args[0] == "compose" && args[1] == "-p" && args[2] == project && slices.Contains(args, "down") {
			return true
		}
	}
	return false
}

func TestRunEndRemovesTheWorktreesServices(t *testing.T) {
	dockerLog := useFakeDocker(t)
	cache := t.TempDir()
	e := newEnvWithCache(t, `[{"say":"done"}]`, 1, cache)
	p := writeRecord(t, cache, e.worktree("MEG-1"), os.Getpid())
	other := writeRecord(t, cache, e.worktree("MEG-2"), os.Getpid())
	e.startRun("run-1", "MEG-1", "workspace")
	if f := e.finished("run-1"); f.Outcome != "completed" {
		t.Fatalf("finished = %+v", f)
	}
	if !downCalled(t, dockerLog, p) {
		t.Fatalf("no compose down for %s: %q", p, dockerCalls(t, dockerLog))
	}
	if recordExists(cache, p) {
		t.Error("the run's worktree record is still there")
	}
	if !recordExists(cache, other) {
		t.Error("another worktree's record was removed")
	}
}

func TestCancelledRunRemovesTheWorktreesServices(t *testing.T) {
	useFakeDocker(t)
	cache := t.TempDir()
	e := newEnvWithCache(t, `[{"say":"hi"},{"sleep_ms":30000}]`, 1, cache)
	p := writeRecord(t, cache, e.worktree("MEG-1"), os.Getpid())
	e.startRun("run-1", "MEG-1", "workspace")
	e.waitUpdate("run-1")
	if err := e.srv.Send(protocol.RunCancel{Type: protocol.TypeRunCancel, RunID: "run-1"}); err != nil {
		t.Fatal(err)
	}
	if f := e.finished("run-1"); f.Outcome != "cancelled" {
		t.Fatalf("finished = %+v", f)
	}
	if recordExists(cache, p) {
		t.Error("the cancelled run's worktree record is still there")
	}
}

// lockedBuffer is a bytes.Buffer safe for the manager's goroutines.
type lockedBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *lockedBuffer) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}

func (l *lockedBuffer) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.String()
}

func TestRemovalFailureIsLoggedAndKept(t *testing.T) {
	useFakeDocker(t)
	t.Setenv("FAKEDOCKER_FAIL", "down,rm")
	t.Setenv("FAKEDOCKER_LEFTOVER", "1")
	cache := t.TempDir()
	var log lockedBuffer
	e := newEnvWithCache(t, `[{"say":"done"}]`, 1, cache, func(m *Manager) { m.Log = &log })
	p := writeRecord(t, cache, e.worktree("MEG-1"), os.Getpid())
	e.startRun("run-1", "MEG-1", "workspace")
	if f := e.finished("run-1"); f.Outcome != "completed" {
		t.Fatalf("finished = %+v", f)
	}
	if !recordExists(cache, p) {
		t.Error("the record is gone although its removal failed")
	}
	if l := e.runLog("run-1"); !strings.Contains(l, "runner: services:") {
		t.Errorf("run log = %q", l)
	}
	if !strings.Contains(log.String(), p) {
		t.Errorf("manager log = %q", log.String())
	}
}

func TestServeSweepsDeadServices(t *testing.T) {
	useFakeDocker(t)
	cache := t.TempDir()
	cmd := exec.Command("git", "--version")
	if err := cmd.Run(); err != nil {
		t.Fatal(err)
	}
	p := writeRecord(t, cache, filepath.Join(t.TempDir(), "gone"), cmd.Process.Pid)
	newEnvWithCache(t, `[]`, 1, cache)
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if !recordExists(cache, p) {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("the dead process's services were not swept")
}

func TestDraftRunsSkipServices(t *testing.T) {
	dockerLog := useFakeDocker(t)
	cache := t.TempDir()
	e := newEnvWithCache(t, `[{"say":"drafted"}]`, 1, cache)
	p := writeRecord(t, cache, e.draftFolder(), os.Getpid())
	e.startDraftRun("run-1", "")
	if f := e.finished("run-1"); f.Outcome != "completed" {
		t.Fatalf("finished = %+v", f)
	}
	if calls := dockerCalls(t, dockerLog); len(calls) != 0 {
		t.Fatalf("docker calls for a draft run: %q", calls)
	}
	if !recordExists(cache, p) {
		t.Error("a draft run removed services")
	}
}
