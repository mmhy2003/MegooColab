package cmd

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
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

func TestShouldRelaunchHidden(t *testing.T) {
	cases := []struct {
		marker  string
		visible bool
		want    bool
	}{
		{"", true, true},
		{"", false, false},
		{"1", true, false},
		{"1", false, false},
	}
	for _, c := range cases {
		if got := shouldRelaunchHidden(c.marker, c.visible); got != c.want {
			t.Errorf("shouldRelaunchHidden(%q,%v) = %v", c.marker, c.visible, got)
		}
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
