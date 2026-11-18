package jobs

import (
	"bufio"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"

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
	t.Setenv("PATH", testutil.BuildFakeDocker(t)+string(os.PathListSeparator)+os.Getenv("PATH"))
	dockerLog := filepath.Join(t.TempDir(), "docker.log")
	t.Setenv("FAKEDOCKER_LOG", dockerLog)
	for _, name := range []string{"FAKEDOCKER_FAIL", "FAKEDOCKER_LEFTOVER", "FAKEDOCKER_SHOW",
		"FAKEDOCKER_PORT_TAKEN", "FAKEDOCKER_CONFIG", "FAKEDOCKER_UP_SLEEP_MS", "MEGOO_SERVICES_DIR"} {
		t.Setenv(name, "")
	}
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
