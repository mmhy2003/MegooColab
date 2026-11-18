package services

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

const runFile = `[services.test]
compose = ["compose.yml"]
ports = ["DB_PORT"]

[services.test.env]
URL = "x:${DB_PORT}"

[services.web]
compose = ["compose.yml"]
`

// runWorktree writes megoocolab.toml and its Compose file in a new worktree
// and returns the worktree.
func runWorktree(t *testing.T) string {
	t.Helper()
	worktree := Canonical(t.TempDir())
	writeFile(t, worktree, FileName, runFile)
	writeFile(t, worktree, "compose.yml", "services: {}\n")
	return worktree
}

// runOutput is what a Run printed.
type runOutput struct{ stdout, stderr strings.Builder }

// runOptions returns options running the test binary as the command, in
// worktree, for set, with a new records folder.
func runOptions(t *testing.T, worktree, set string, out *runOutput) Options {
	t.Helper()
	return Options{
		Dir:     t.TempDir(),
		Cwd:     worktree,
		Set:     set,
		Command: []string{os.Args[0]},
		Stdout:  &out.stdout,
		Stderr:  &out.stderr,
	}
}

func TestRunPassesVarsAndExitCode(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("FAKEDOCKER_SHOW", "DB_PORT")
	t.Setenv("SERVICES_TEST_HELPER", "env:URL")
	worktree := runWorktree(t)
	var out runOutput
	o := runOptions(t, worktree, "test", &out)

	if code := Run(context.Background(), o); code != 0 {
		t.Fatalf("Run = %d, want 0; stderr:\n%s", code, out.stderr.String())
	}
	cs := loggedCalls(t, log)
	var port string
	for _, c := range cs {
		if slices.Contains(c.Args, "up") {
			port = c.Env["DB_PORT"]
		}
	}
	if port == "" {
		t.Fatalf("no up call with DB_PORT: %v", cs)
	}
	if got, want := out.stdout.String(), "x:"+port+"\n"; got != want {
		t.Errorf("stdout = %q, want %q", got, want)
	}
	vs := verbs(calls(t, log))
	if i, j := slices.Index(vs, "up"), slices.Index(vs, "down"); i < 0 || j < i {
		t.Errorf("want up then down: %q", vs)
	}
	if slices.Contains(vs, "logs") {
		t.Errorf("logs saved after a passing command: %q", vs)
	}
	if recs, err := List(o.Dir); err != nil || len(recs) != 0 {
		t.Errorf("records left: %v, %v", recs, err)
	}
}

func TestRunReturnsTheCommandsFailure(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("SERVICES_TEST_HELPER", "exit:3")
	var out runOutput
	o := runOptions(t, runWorktree(t), "test", &out)

	if code := Run(context.Background(), o); code != 3 {
		t.Fatalf("Run = %d, want 3; stderr:\n%s", code, out.stderr.String())
	}
	logPath := filepath.Join(o.Dir, "logs", ProjectName(o.Cwd, "test")+".log")
	if !exists(logPath) {
		t.Error("logs not saved after a failing command")
	}
	if want := "megoocolab-runner services: logs saved to " + logPath; !strings.Contains(out.stderr.String(), want) {
		t.Errorf("stderr %q does not contain %q", out.stderr.String(), want)
	}
	if vs := verbs(calls(t, log)); !slices.Contains(vs, "down") {
		t.Errorf("no down call: %q", vs)
	}
}

func TestRunRefusesASecondRunOfTheSameSet(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("SERVICES_TEST_HELPER", "env:URL")
	var out runOutput
	o := runOptions(t, runWorktree(t), "test", &out)
	if err := Claim(o.Dir, testRecord(t, o.Cwd, "test", os.Getpid())); err != nil {
		t.Fatal(err)
	}

	if code := Run(context.Background(), o); code != ExitServices {
		t.Fatalf("Run = %d, want %d", code, ExitServices)
	}
	if out.stdout.String() != "" {
		t.Errorf("the command ran: stdout %q", out.stdout.String())
	}
	if want := "megoocolab-runner services: test is already running in this worktree"; !strings.Contains(out.stderr.String(), want) {
		t.Errorf("stderr %q does not contain %q", out.stderr.String(), want)
	}
	if vs := verbs(calls(t, log)); slices.Contains(vs, "up") {
		t.Errorf("up called: %q", vs)
	}
}

func TestRunRemovesAfterASignal(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("signals are Unix only")
	}
	log := fakeDocker(t)
	t.Setenv("SERVICES_TEST_HELPER", "sleep")
	var out runOutput
	o := runOptions(t, runWorktree(t), "test", &out)
	signals := make(chan os.Signal, 1)
	o.Signals = signals

	done := make(chan int, 1)
	go func() { done <- Run(context.Background(), o) }()
	deadline := time.Now().Add(20 * time.Second)
	for !slices.Contains(verbs(calls(t, log)), "up") {
		if time.Now().After(deadline) {
			t.Fatal("up never called")
		}
		time.Sleep(20 * time.Millisecond)
	}
	signals <- syscall.SIGTERM

	select {
	case code := <-done:
		if code != 128+int(syscall.SIGTERM) {
			t.Errorf("Run = %d, want %d; stderr:\n%s", code, 128+int(syscall.SIGTERM), out.stderr.String())
		}
	case <-time.After(20 * time.Second):
		t.Fatal("Run did not end after SIGTERM")
	}
	if vs := verbs(calls(t, log)); !slices.Contains(vs, "down") {
		t.Errorf("no down call: %q", vs)
	}
}

func TestRunFailedStartIs125(t *testing.T) {
	fakeDocker(t)
	t.Setenv("FAKEDOCKER_FAIL", "up")
	t.Setenv("SERVICES_TEST_HELPER", "env:URL")
	var out runOutput
	o := runOptions(t, runWorktree(t), "test", &out)

	if code := Run(context.Background(), o); code != ExitServices {
		t.Fatalf("Run = %d, want %d", code, ExitServices)
	}
	if out.stdout.String() != "" {
		t.Errorf("the command ran: stdout %q", out.stdout.String())
	}
}

func TestRunRemovalFailureIs125(t *testing.T) {
	fakeDocker(t)
	t.Setenv("FAKEDOCKER_FAIL", "down,rm")
	t.Setenv("FAKEDOCKER_LEFTOVER", "1")
	t.Setenv("SERVICES_TEST_HELPER", "exit:0")
	var out runOutput
	o := runOptions(t, runWorktree(t), "test", &out)

	if code := Run(context.Background(), o); code != ExitServices {
		t.Fatalf("Run = %d, want %d", code, ExitServices)
	}
	if !exists(filepath.Join(o.Dir, ProjectName(o.Cwd, "test")+".json")) {
		t.Error("record deleted although removal failed")
	}
	if want := "the services stay recorded; megoocolab-runner services clean retries"; !strings.Contains(out.stderr.String(), want) {
		t.Errorf("stderr %q does not contain %q", out.stderr.String(), want)
	}
}

func TestRunErrorsBeforeStarting(t *testing.T) {
	worktree := runWorktree(t)
	cases := []struct {
		name  string
		cwd   string
		set   string
		setup func(t *testing.T)
		want  string
	}{
		{"no file", t.TempDir(), "test", nil, "no megoocolab.toml"},
		{"unknown set", worktree, "nope", nil,
			filepath.Join(worktree, FileName) + `: no service set "nope" (sets: test, web)`},
		{"docker missing", worktree, "test", func(t *testing.T) { t.Setenv("PATH", t.TempDir()) },
			"Docker is not installed"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			log := fakeDocker(t)
			t.Setenv("SERVICES_TEST_HELPER", "env:URL")
			if c.setup != nil {
				c.setup(t)
			}
			var out runOutput
			o := runOptions(t, c.cwd, c.set, &out)

			if code := Run(context.Background(), o); code != ExitServices {
				t.Fatalf("Run = %d, want %d", code, ExitServices)
			}
			if want := "megoocolab-runner services: "; !strings.HasPrefix(out.stderr.String(), want) {
				t.Errorf("stderr %q does not start with %q", out.stderr.String(), want)
			}
			if !strings.Contains(out.stderr.String(), c.want) {
				t.Errorf("stderr %q does not contain %q", out.stderr.String(), c.want)
			}
			if vs := verbs(calls(t, log)); slices.Contains(vs, "up") {
				t.Errorf("up called: %q", vs)
			}
			if out.stdout.String() != "" {
				t.Errorf("the command ran: stdout %q", out.stdout.String())
			}
		})
	}
}

func TestRunNeedsACommand(t *testing.T) {
	log := fakeDocker(t)
	var out runOutput
	o := runOptions(t, runWorktree(t), "test", &out)
	o.Command = nil

	if code := Run(context.Background(), o); code != ExitServices {
		t.Fatalf("Run = %d, want %d", code, ExitServices)
	}
	if got := calls(t, log); len(got) != 0 {
		t.Errorf("docker called: %q", got)
	}
}

func TestRunMissingCommandIs127(t *testing.T) {
	log := fakeDocker(t)
	var out runOutput
	o := runOptions(t, runWorktree(t), "test", &out)
	o.Command = []string{"megoo-no-such-program-" + strconv.Itoa(os.Getpid())}

	if code := Run(context.Background(), o); code != 127 {
		t.Fatalf("Run = %d, want 127", code)
	}
	if vs := verbs(calls(t, log)); !slices.Contains(vs, "down") {
		t.Errorf("no down call: %q", vs)
	}
}

func TestRunSweepsDeadRecordsFirst(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("SERVICES_TEST_HELPER", "exit:0")
	stubAlive(t, func(pid int) bool { return pid != 1111 })
	var out runOutput
	o := runOptions(t, runWorktree(t), "test", &out)
	dead := recordOnDisk(t, o.Dir, t.TempDir(), "test", 1111)

	if code := Run(context.Background(), o); code != 0 {
		t.Fatalf("Run = %d, want 0; stderr:\n%s", code, out.stderr.String())
	}
	cs := calls(t, log)
	vs := verbs(cs)
	up := slices.Index(vs, "up")
	removed := slices.IndexFunc(cs, func(args []string) bool {
		return slices.Contains(args, dead.Project) && slices.Contains(args, "down")
	})
	if removed < 0 || up < 0 || removed > up {
		t.Errorf("dead set not removed before up: %q", cs)
	}
	if exists(filepath.Join(o.Dir, dead.Project+".json")) {
		t.Error("dead record left")
	}
}
