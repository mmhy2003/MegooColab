package cmd

import (
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
)

func TestServiceConfig(t *testing.T) {
	c := serviceConfig("/opt/node/bin:/usr/bin")
	if c.Name != "megoocolab-runner" {
		t.Errorf("Name = %q", c.Name)
	}
	if c.DisplayName != "MegooColab Runner" {
		t.Errorf("DisplayName = %q", c.DisplayName)
	}
	if v, ok := c.Option["UserService"].(bool); !ok || !v {
		t.Errorf("UserService option = %v, want true", c.Option["UserService"])
	}
	if !reflect.DeepEqual(c.Arguments, []string{"run"}) {
		t.Errorf("Arguments = %v", c.Arguments)
	}
	if got := c.EnvVars["PATH"]; got != "/opt/node/bin:/usr/bin" {
		t.Errorf("EnvVars[PATH] = %q", got)
	}
	script, _ := c.Option["SystemdScript"].(string)
	if !strings.Contains(script, "WantedBy=default.target") || strings.Contains(script, "multi-user.target") {
		t.Errorf("SystemdScript must install into default.target:\n%s", script)
	}
	if !strings.Contains(script, "ExecStart={{Path | cmdEscape}}") {
		t.Errorf("SystemdScript lost ExecStart")
	}
}

func TestRunValue(t *testing.T) {
	got := runValue(`C:\Users\me\My Tools\megoocolab-runner.exe`)
	want := `"C:\Users\me\My Tools\megoocolab-runner.exe" run --background`
	if got != want {
		t.Errorf("runValue = %q, want %q", got, want)
	}
}

func TestParsePID(t *testing.T) {
	for in, want := range map[string]int{"123": 123, " 42\r\n": 42} {
		if pid, ok := parsePID([]byte(in)); !ok || pid != want {
			t.Errorf("parsePID(%q) = %d, %v", in, pid, ok)
		}
	}
	for _, in := range []string{"", "abc", "0", "-5", "12 34"} {
		if _, ok := parsePID([]byte(in)); ok {
			t.Errorf("parsePID(%q) should fail", in)
		}
	}
}

func TestStatusText(t *testing.T) {
	cases := []struct {
		installed, running bool
		pid                int
		want               string
	}{
		{false, false, 0, "not installed"},
		{true, false, 0, "stopped"},
		{true, true, 7, "running (pid 7)"},
		{false, true, 7, "running (pid 7)"},
	}
	for _, c := range cases {
		if got := statusText(c.installed, c.running, c.pid); got != c.want {
			t.Errorf("statusText(%v,%v,%d) = %q, want %q", c.installed, c.running, c.pid, got, c.want)
		}
	}
}

func TestSameFile(t *testing.T) {
	dir := t.TempDir()
	real := filepath.Join(dir, "real")
	if err := os.Mkdir(real, 0o700); err != nil {
		t.Fatal(err)
	}
	exe := filepath.Join(real, "runner.exe")
	other := filepath.Join(real, "other.exe")
	for _, f := range []string{exe, other} {
		if err := os.WriteFile(f, []byte("x"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	if !sameFile(exe, exe) {
		t.Error("a file is the same file as itself")
	}
	if sameFile(exe, other) {
		t.Error("different files matched")
	}
	if sameFile(exe, filepath.Join(real, "missing.exe")) {
		t.Error("a missing file matched")
	}
	if runtime.GOOS == "windows" && !sameFile(exe, strings.ToUpper(exe)) {
		t.Error("case difference should match on Windows")
	}
	// Scoop runs the app through a "current" junction.
	link := filepath.Join(dir, "current")
	if runtime.GOOS == "windows" {
		if out, err := exec.Command("cmd", "/c", "mklink", "/J", link, real).CombinedOutput(); err != nil {
			t.Skipf("cannot create a junction: %v %s", err, out)
		}
	} else if err := os.Symlink(real, link); err != nil {
		t.Skipf("cannot create a symlink: %v", err)
	}
	if !sameFile(filepath.Join(link, "runner.exe"), exe) {
		t.Error("a path through a junction/symlink must match the real path")
	}
}

func TestBackgroundRole(t *testing.T) {
	cases := []struct {
		goos, marker string
		want         bgRole
	}{
		{"windows", "", roleLauncher},
		{"windows", "1", roleSupervisor},
		{"windows", workerMarker, roleWorker},
		{"linux", "", roleSingle},
		{"darwin", "1", roleSingle},
	}
	for _, c := range cases {
		if got := backgroundRole(c.goos, c.marker); got != c.want {
			t.Errorf("backgroundRole(%q, %q) = %v, want %v", c.goos, c.marker, got, c.want)
		}
	}
}

func TestRunServiceWorkerSkipsPidFile(t *testing.T) {
	stubLoadConfig(t)
	orig := os.Stderr
	t.Cleanup(func() { os.Stderr = orig })
	stderr, err := os.Create(filepath.Join(t.TempDir(), "stderr.log"))
	if err != nil {
		t.Fatal(err)
	}
	defer stderr.Close()
	os.Stderr = stderr

	root := t.TempDir()
	_ = runServiceAt(context.Background(), roleWorker, "9.9.9", root, nil, t.TempDir())
	if fileExists(pidPath(root)) {
		t.Errorf("the worker wrote %s; only the supervisor owns the pid file", pidPath(root))
	}
}

func TestSystemdEnvLine(t *testing.T) {
	c := serviceConfig(`/opt/my tools/bin:/100%:/q"x`)
	script := c.Option["SystemdScript"].(string)
	want := `Environment="PATH=/opt/my tools/bin:/100%%:/q` + "\\" + `"x"`
	if !strings.Contains(script, want) {
		t.Errorf("missing %s in: %s", want, script)
	}
	if strings.Contains(script, "{{ENV}}") || strings.Contains(script, "EnvVars") {
		t.Errorf("template placeholders left in script")
	}
	if strings.Contains(serviceConfig("").Option["SystemdScript"].(string), "Environment=") {
		t.Errorf("empty PATH must not emit an Environment line")
	}
}

func TestWatchStopFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runner.stop")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan struct{})
	go func() { watchStopFile(ctx, path, 10*time.Millisecond, cancel); close(done) }()
	time.Sleep(30 * time.Millisecond)
	select {
	case <-ctx.Done():
		t.Fatal("cancelled before the stop file existed")
	default:
	}
	if err := os.WriteFile(path, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	select {
	case <-ctx.Done():
	case <-time.After(2 * time.Second):
		t.Fatal("stop file did not cancel the context")
	}
	<-done
}

func TestPidFileLifecycle(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(stopPath(root), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	cleanup, err := beginBackground(root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(stopPath(root)); !os.IsNotExist(err) {
		t.Errorf("stale stop file not removed: %v", err)
	}
	b, err := os.ReadFile(pidPath(root))
	if err != nil {
		t.Fatal(err)
	}
	if pid, ok := parsePID(b); !ok || pid != os.Getpid() {
		t.Errorf("pid file = %q", b)
	}
	if err := os.WriteFile(pidPath(root), []byte("999999"), 0o600); err != nil {
		t.Fatal(err)
	}
	cleanup()
	if _, err := os.Stat(pidPath(root)); err != nil {
		t.Errorf("another runner's pid file must be left alone: %v", err)
	}
	if err := os.WriteFile(pidPath(root), []byte(strconv.Itoa(os.Getpid())), 0o600); err != nil {
		t.Fatal(err)
	}
	cleanup()
	if _, err := os.Stat(pidPath(root)); !os.IsNotExist(err) {
		t.Errorf("own pid file not removed: %v", err)
	}
}

func TestOpenRunLogTruncatesWhenLarge(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "logs", "runner.log")
	appendLog := func(s string) {
		t.Helper()
		w, err := openRunLog(dir)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := w.Write([]byte(s)); err != nil {
			t.Fatal(err)
		}
		if err := w.Close(); err != nil {
			t.Fatal(err)
		}
	}
	appendLog("hello\n")
	appendLog("again\n")
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "hello\nagain\n" {
		t.Fatalf("append failed: %q", b)
	}
	if err := os.WriteFile(path, make([]byte, maxLogBytes+1), 0o600); err != nil {
		t.Fatal(err)
	}
	appendLog("fresh\n")
	b, err = os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "fresh\n" {
		t.Fatalf("not truncated: %d bytes", len(b))
	}
}

// fakeManager records the calls the shared install/start flow makes.
type fakeManager struct {
	calls    []string
	status   string
	startErr error
}

func (f *fakeManager) Install() error   { f.calls = append(f.calls, "install"); return nil }
func (f *fakeManager) Uninstall() error { f.calls = append(f.calls, "uninstall"); return nil }
func (f *fakeManager) Stop() error      { f.calls = append(f.calls, "stop"); return nil }

func (f *fakeManager) Start() error {
	f.calls = append(f.calls, "start")
	if f.startErr != nil {
		return f.startErr
	}
	f.status = "running (pid 1)"
	return nil
}

func (f *fakeManager) Status() (string, error) {
	f.calls = append(f.calls, "status")
	return f.status, nil
}

// stubLoggedIn makes loadConfig return a usable login for one test.
func stubLoggedIn(t *testing.T) {
	t.Helper()
	orig := loadConfig
	t.Cleanup(func() { loadConfig = orig })
	loadConfig = func() (config.Config, error) {
		return config.Config{URL: "https://colab.example", Token: "t"}, nil
	}
}

func TestServiceInstallRefusesWithoutLogin(t *testing.T) {
	stubLoadConfig(t)
	m := &fakeManager{status: "not installed"}
	var out strings.Builder
	err := serviceInstall(m, &out)
	if !errors.Is(err, errNotLoggedIn) {
		t.Fatalf("err = %v, want errNotLoggedIn", err)
	}
	if !strings.HasPrefix(err.Error(), "service install: not logged in") {
		t.Errorf("err = %q", err)
	}
	if len(m.calls) != 0 {
		t.Errorf("calls = %v, want none", m.calls)
	}
	if out.Len() != 0 {
		t.Errorf("out = %q, want nothing", out.String())
	}
}

func TestServiceInstallRegistersThenStarts(t *testing.T) {
	stubLoggedIn(t)
	m := &fakeManager{status: "stopped"}
	var out strings.Builder
	if err := serviceInstall(m, &out); err != nil {
		t.Fatal(err)
	}
	if want := []string{"install", "start", "status"}; !reflect.DeepEqual(m.calls, want) {
		t.Errorf("calls = %v, want %v", m.calls, want)
	}
	for _, want := range []string{"service install: ok", "running (pid 1)"} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("out = %q, want it to contain %q", out.String(), want)
		}
	}
}

func TestServiceInstallReportsStartFailure(t *testing.T) {
	stubLoggedIn(t)
	m := &fakeManager{status: "stopped", startErr: errors.New("boom")}
	err := serviceInstall(m, io.Discard)
	if err == nil || !strings.HasPrefix(err.Error(), "service start:") {
		t.Fatalf("err = %v, want a service start: error", err)
	}
}

func TestServiceStartWhenRunning(t *testing.T) {
	stubLoggedIn(t)
	m := &fakeManager{status: "running (pid 9)"}
	var out strings.Builder
	if err := serviceStart(m, &out); err != nil {
		t.Fatal(err)
	}
	if out.String() != "already running\n" {
		t.Errorf("out = %q", out.String())
	}
	for _, c := range m.calls {
		if c == "start" {
			t.Errorf("calls = %v, want no start", m.calls)
		}
	}
}

func TestServiceStartWhenStopped(t *testing.T) {
	stubLoggedIn(t)
	m := &fakeManager{status: "stopped"}
	var out strings.Builder
	if err := serviceStart(m, &out); err != nil {
		t.Fatal(err)
	}
	if want := []string{"status", "start"}; !reflect.DeepEqual(m.calls, want) {
		t.Errorf("calls = %v, want %v", m.calls, want)
	}
	if !strings.Contains(out.String(), "service start: ok") {
		t.Errorf("out = %q", out.String())
	}
}

func TestServiceStartRefusesWithoutLogin(t *testing.T) {
	stubLoadConfig(t)
	m := &fakeManager{status: "stopped"}
	var out strings.Builder
	err := serviceStart(m, &out)
	if !errors.Is(err, errNotLoggedIn) {
		t.Fatalf("err = %v, want errNotLoggedIn", err)
	}
	if len(m.calls) != 0 || out.Len() != 0 {
		t.Errorf("calls = %v, out = %q; want nothing", m.calls, out.String())
	}
}
