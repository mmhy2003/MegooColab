package cmd

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/services"
	"github.com/mmhy2003/megoocolab/runner/internal/testutil"
)

// servicesEnv puts the fake docker first on PATH, points MEGOO_SERVICES_DIR
// at a new folder and returns that folder.
func servicesEnv(t *testing.T) string {
	t.Helper()
	t.Setenv("PATH", testutil.BuildFakeDocker(t)+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("FAKEDOCKER_LOG", filepath.Join(t.TempDir(), "docker.log"))
	for _, name := range []string{"FAKEDOCKER_FAIL", "FAKEDOCKER_LEFTOVER", "FAKEDOCKER_SHOW",
		"FAKEDOCKER_PORT_TAKEN", "FAKEDOCKER_CONFIG", "FAKEDOCKER_UP_SLEEP_MS"} {
		t.Setenv(name, "")
	}
	dir := t.TempDir()
	t.Setenv("MEGOO_SERVICES_DIR", dir)
	return dir
}

// servicesWorktree writes megoocolab.toml with a set `test` and its Compose
// file in a new folder and makes it the current directory.
func servicesWorktree(t *testing.T) string {
	t.Helper()
	wt := services.Canonical(t.TempDir())
	files := map[string]string{
		services.FileName: "[services.test]\ncompose = [\"compose.yml\"]\nports = [\"DB_PORT\"]\n",
		"compose.yml":     "services: {}\n",
	}
	for name, body := range files {
		if err := os.WriteFile(filepath.Join(wt, name), []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	t.Chdir(wt)
	return wt
}

// runServices runs the root command with args and returns its error and
// what it printed.
func runServices(t *testing.T, args ...string) (error, string, string) {
	t.Helper()
	var stdout, stderr bytes.Buffer
	root := newRootCmd("test")
	root.SetArgs(args)
	root.SetOut(&stdout)
	root.SetErr(&stderr)
	root.SetIn(strings.NewReader(""))
	err := root.Execute()
	return err, stdout.String(), stderr.String()
}

func TestServicesRunExitsWithTheCommandsCode(t *testing.T) {
	servicesEnv(t)
	servicesWorktree(t)

	if err, _, stderr := runServices(t, "services", "run", "test", "--", "git", "--version"); err != nil {
		t.Fatalf("services run = %v, want nil; stderr:\n%s", err, stderr)
	}

	err, _, _ := runServices(t, "services", "run", "test", "--", "git", "definitely-not-a-git-command")
	var e exitError
	if !errors.As(err, &e) || e.code != 1 {
		t.Fatalf("services run = %v, want exitError code 1", err)
	}
}

func TestServicesRunNeedsADash(t *testing.T) {
	servicesEnv(t)
	servicesWorktree(t)
	for _, args := range [][]string{
		{"services", "run", "test", "git"},
		{"services", "run", "--", "git"},
	} {
		err, _, _ := runServices(t, args...)
		if err == nil || !strings.Contains(err.Error(), "use: megoocolab-runner services run <name> -- <command...>") {
			t.Errorf("%q: err = %v, want the usage error", args, err)
		}
		var e exitError
		if errors.As(err, &e) {
			t.Errorf("%q: usage error is an exitError", args)
		}
	}
}

// deadPID returns the PID of a process that has ended.
func deadPID(t *testing.T) int {
	t.Helper()
	cmd := exec.Command("git", "--version")
	if err := cmd.Run(); err != nil {
		t.Fatal(err)
	}
	return cmd.Process.Pid
}

// writeRecord writes a record of the set `test` of a new worktree, started by
// pid, into dir.
func writeRecord(t *testing.T, dir string, pid int) services.Record {
	t.Helper()
	wt := services.Canonical(t.TempDir())
	rec := services.Record{Project: services.ProjectName(wt, "test"), Worktree: wt, Set: "test", PID: pid}
	if err := services.Claim(dir, rec); err != nil {
		t.Fatal(err)
	}
	return rec
}

func TestServicesClean(t *testing.T) {
	dir := servicesEnv(t)
	rec := writeRecord(t, dir, deadPID(t))

	err, stdout, stderr := runServices(t, "services", "clean")
	if err != nil {
		t.Fatalf("services clean = %v; stderr:\n%s", err, stderr)
	}
	if want := "removed " + rec.Project + "\n"; stdout != want {
		t.Errorf("stdout = %q, want %q", stdout, want)
	}
	if _, err := os.Stat(filepath.Join(dir, rec.Project+".json")); !os.IsNotExist(err) {
		t.Errorf("record still there: %v", err)
	}

	left := writeRecord(t, dir, deadPID(t))
	t.Setenv("FAKEDOCKER_FAIL", "down,rm")
	t.Setenv("FAKEDOCKER_LEFTOVER", "1")
	err, stdout, stderr = runServices(t, "services", "clean")
	var e exitError
	if !errors.As(err, &e) || e.code != services.ExitServices {
		t.Fatalf("services clean = %v, want exitError %d", err, services.ExitServices)
	}
	if stdout != "" {
		t.Errorf("stdout = %q, want nothing removed", stdout)
	}
	if !strings.Contains(stderr, left.Project) {
		t.Errorf("stderr does not name %s:\n%s", left.Project, stderr)
	}
	data, err := os.ReadFile(filepath.Join(dir, left.Project+".json"))
	if err != nil {
		t.Fatalf("record removed after a failure: %v", err)
	}
	var kept services.Record
	if err := json.Unmarshal(data, &kept); err != nil || kept.Project != left.Project {
		t.Errorf("record = %s, %v", data, err)
	}
}

func TestExecuteExitError(t *testing.T) {
	if code, ok := exitStatus(exitError{code: 3}); !ok || code != 3 {
		t.Errorf("exitStatus(exitError{3}) = %d, %v; want 3, true", code, ok)
	}
	if got := (exitError{code: 3}).Error(); got != "exit status 3" {
		t.Errorf("Error() = %q", got)
	}
	if _, ok := exitStatus(errors.New("boom")); ok {
		t.Error("exitStatus(other error) is ok")
	}
}
