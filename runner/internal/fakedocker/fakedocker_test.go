package main_test

import (
	"bufio"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/testutil"
)

type call struct {
	Args []string          `json:"args"`
	Env  map[string]string `json:"env"`
}

// fake runs the built fake docker with args and extra env, writing its log to
// log. It returns stdout, stderr and the exit code.
func fake(t *testing.T, log string, env []string, args ...string) (string, string, int) {
	t.Helper()
	name := "docker"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	cmd := exec.Command(filepath.Join(testutil.BuildFakeDocker(t), name), args...)
	cmd.Env = append(append(os.Environ(), "FAKEDOCKER_LOG="+log), env...)
	var out, errOut strings.Builder
	cmd.Stdout, cmd.Stderr = &out, &errOut
	err := cmd.Run()
	code := 0
	if ee, ok := err.(*exec.ExitError); ok {
		code = ee.ExitCode()
	} else if err != nil {
		t.Fatalf("run fake docker: %v", err)
	}
	return out.String(), errOut.String(), code
}

func readLog(t *testing.T, log string) []call {
	t.Helper()
	f, err := os.Open(log)
	if err != nil {
		t.Fatalf("open log: %v", err)
	}
	defer f.Close()
	var calls []call
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		var c call
		if err := json.Unmarshal(sc.Bytes(), &c); err != nil {
			t.Fatalf("log line %q: %v", sc.Text(), err)
		}
		calls = append(calls, c)
	}
	return calls
}

func TestLogsEachCallWithItsArgsAndShownEnv(t *testing.T) {
	log := filepath.Join(t.TempDir(), "log")
	args := []string{"compose", "-p", "p", "-f", "a.yml", "up", "-d"}
	_, _, code := fake(t, log, []string{"FAKEDOCKER_SHOW=DB_PORT,UNSET_NAME", "DB_PORT=1234", "OTHER=x"}, args...)
	if code != 0 {
		t.Fatalf("exit %d", code)
	}
	calls := readLog(t, log)
	if len(calls) != 1 {
		t.Fatalf("got %d log lines, want 1", len(calls))
	}
	if !reflect.DeepEqual(calls[0].Args, args) {
		t.Errorf("args = %q, want %q", calls[0].Args, args)
	}
	if want := map[string]string{"DB_PORT": "1234"}; !reflect.DeepEqual(calls[0].Env, want) {
		t.Errorf("env = %v, want %v", calls[0].Env, want)
	}
}

func TestFailsTheNamedVerbs(t *testing.T) {
	log := filepath.Join(t.TempDir(), "log")
	env := []string{"FAKEDOCKER_FAIL=up,rm"}
	_, stderr, code := fake(t, log, env, "compose", "-p", "p", "up")
	if code != 1 || !strings.Contains(stderr, "fakedocker: up failed") {
		t.Errorf("up: exit %d, stderr %q", code, stderr)
	}
	if _, stderr, code = fake(t, log, env, "compose", "-p", "p", "down"); code != 0 {
		t.Errorf("down: exit %d, stderr %q", code, stderr)
	}
	if _, stderr, code = fake(t, log, env, "rm", "-f", "x"); code != 1 || !strings.Contains(stderr, "fakedocker: rm failed") {
		t.Errorf("rm: exit %d, stderr %q", code, stderr)
	}
	if n := len(readLog(t, log)); n != 3 {
		t.Errorf("got %d log lines, want 3", n)
	}
}

func TestPortTakenOnlyForTheFirstUps(t *testing.T) {
	log := filepath.Join(t.TempDir(), "log")
	env := []string{"FAKEDOCKER_PORT_TAKEN=2"}
	for i := 0; i < 2; i++ {
		_, stderr, code := fake(t, log, env, "compose", "-p", "p", "--env-file", "e", "up", "-d")
		if code != 1 || !strings.Contains(stderr, "port is already allocated") {
			t.Fatalf("up %d: exit %d, stderr %q", i+1, code, stderr)
		}
	}
	if _, stderr, code := fake(t, log, env, "compose", "-p", "p", "up", "-d"); code != 0 {
		t.Errorf("third up: exit %d, stderr %q", code, stderr)
	}
}

func TestConfigAndLeftovers(t *testing.T) {
	log := filepath.Join(t.TempDir(), "log")
	cfg := `{"name":"p","services":{"db":{}}}`
	out, _, code := fake(t, log, []string{"FAKEDOCKER_CONFIG=" + cfg}, "compose", "-p", "p", "-f", "a.yml", "config", "--format", "json")
	if code != 0 || strings.TrimSpace(out) != cfg {
		t.Errorf("config: exit %d, out %q", code, out)
	}
	out, _, _ = fake(t, log, nil, "compose", "config", "--format", "json")
	if strings.TrimSpace(out) != `{"name":"x","services":{}}` {
		t.Errorf("default config = %q", out)
	}

	if out, _, code := fake(t, log, nil, "ps", "-aq"); code != 0 || out != "" {
		t.Errorf("ps: exit %d, out %q", code, out)
	}
	left := []string{"FAKEDOCKER_LEFTOVER=1"}
	for _, args := range [][]string{{"ps", "-aq"}, {"volume", "ls", "-q"}, {"network", "ls", "-q"}} {
		if out, _, code := fake(t, log, left, args...); code != 0 || strings.TrimSpace(out) != "leftover1" {
			t.Errorf("%v: exit %d, out %q", args, code, out)
		}
	}
	if out, _, _ := fake(t, log, nil, "compose", "-p", "p", "logs"); strings.TrimSpace(out) != "fake logs" {
		t.Errorf("logs = %q", out)
	}
}
