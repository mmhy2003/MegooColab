package services

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/testutil"
)

// fakeDocker puts the fake docker first on PATH and returns the file it logs
// each call to.
func fakeDocker(t *testing.T) string {
	t.Helper()
	t.Setenv("PATH", testutil.BuildFakeDocker(t)+string(os.PathListSeparator)+os.Getenv("PATH"))
	log := filepath.Join(t.TempDir(), "docker.log")
	t.Setenv("FAKEDOCKER_LOG", log)
	for _, name := range []string{"FAKEDOCKER_FAIL", "FAKEDOCKER_LEFTOVER", "FAKEDOCKER_SHOW"} {
		t.Setenv(name, "")
	}
	return log
}

// calls returns the arguments of each docker call logged so far.
func calls(t *testing.T, log string) [][]string {
	t.Helper()
	f, err := os.Open(log)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var out [][]string
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		var line struct{ Args []string }
		if err := json.Unmarshal(sc.Bytes(), &line); err != nil {
			t.Fatalf("log line %q: %v", sc.Text(), err)
		}
		out = append(out, line.Args)
	}
	return out
}

// recordOnDisk claims a record with a Compose file and an env file on disk.
func recordOnDisk(t *testing.T, dir, worktree, set string, pid int) Record {
	t.Helper()
	rec := testRecord(t, worktree, set, pid)
	rec.Compose = []string{filepath.Join(worktree, "compose.yml")}
	rec.EnvFile = filepath.Join(dir, rec.Project+".env")
	if err := os.WriteFile(rec.Compose[0], []byte("services: {}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(rec.EnvFile, []byte("A='1'\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := Claim(dir, rec); err != nil {
		t.Fatalf("Claim: %v", err)
	}
	return rec
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func wantCalls(t *testing.T, got, want [][]string) {
	t.Helper()
	if !slices.EqualFunc(got, want, slices.Equal) {
		t.Errorf("docker calls:\n got %q\nwant %q", got, want)
	}
}

func TestRemoveCallsDownThenLabelSweepThenImages(t *testing.T) {
	log := fakeDocker(t)
	dir := t.TempDir()
	rec := recordOnDisk(t, dir, t.TempDir(), "test", os.Getpid())
	rec.Built = []string{"img:p"}
	if err := Remove(context.Background(), dir, rec); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	label := "label=com.docker.compose.project=" + rec.Project
	wantCalls(t, calls(t, log), [][]string{
		{"compose", "-p", rec.Project, "--env-file", rec.EnvFile, "-f", rec.Compose[0], "down", "--volumes", "--remove-orphans", "--timeout", "10"},
		{"ps", "-aq", "--filter", label},
		{"volume", "ls", "-q", "--filter", label},
		{"network", "ls", "-q", "--filter", label},
		{"image", "rm", "img:p"},
	})
	if exists(filepath.Join(dir, rec.Project+".json")) || exists(rec.EnvFile) {
		t.Error("record or env file left after Remove")
	}
}

func TestRemoveWithoutComposeFilesUsesTheProjectOnly(t *testing.T) {
	log := fakeDocker(t)
	dir := t.TempDir()
	rec := recordOnDisk(t, dir, t.TempDir(), "test", os.Getpid())
	if err := os.Remove(rec.Compose[0]); err != nil {
		t.Fatal(err)
	}
	if err := Remove(context.Background(), dir, rec); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	got := calls(t, log)
	if len(got) == 0 {
		t.Fatal("no docker call")
	}
	want := []string{"compose", "-p", rec.Project, "down", "--volumes", "--remove-orphans", "--timeout", "10"}
	if !slices.Equal(got[0], want) {
		t.Errorf("first call = %q, want %q", got[0], want)
	}
	if slices.ContainsFunc(got, func(c []string) bool { return c[0] == "image" }) {
		t.Errorf("image rm called with no built images: %q", got)
	}
}

func TestRemoveRemovesLeftovers(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("FAKEDOCKER_LEFTOVER", "1")
	dir := t.TempDir()
	rec := recordOnDisk(t, dir, t.TempDir(), "test", os.Getpid())
	if err := Remove(context.Background(), dir, rec); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	label := "label=com.docker.compose.project=" + rec.Project
	wantCalls(t, calls(t, log)[1:], [][]string{
		{"ps", "-aq", "--filter", label},
		{"rm", "-f", "-v", "leftover1"},
		{"volume", "ls", "-q", "--filter", label},
		{"volume", "rm", "-f", "leftover1"},
		{"network", "ls", "-q", "--filter", label},
		{"network", "rm", "leftover1"},
	})
}

func TestRemoveFailureKeepsTheRecord(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("FAKEDOCKER_LEFTOVER", "1")
	t.Setenv("FAKEDOCKER_FAIL", "down,rm")
	dir := t.TempDir()
	rec := recordOnDisk(t, dir, t.TempDir(), "test", os.Getpid())
	err := Remove(context.Background(), dir, rec)
	if err == nil {
		t.Fatal("Remove succeeded with failing docker calls")
	}
	if !strings.Contains(err.Error(), "fakedocker: down failed") || !strings.Contains(err.Error(), "fakedocker: rm failed") {
		t.Errorf("error %q does not name both failures", err)
	}
	if !exists(filepath.Join(dir, rec.Project+".json")) || !exists(rec.EnvFile) {
		t.Error("record or env file deleted after a failed Remove")
	}
	if !slices.ContainsFunc(calls(t, log), func(c []string) bool { return slices.Equal(c, []string{"network", "rm", "leftover1"}) }) {
		t.Error("Remove stopped at the first failure")
	}
}

func TestRemoveTreatsMissingImagesAsRemoved(t *testing.T) {
	fakeDocker(t)
	t.Setenv("FAKEDOCKER_FAIL", "image")
	dir := t.TempDir()
	rec := recordOnDisk(t, dir, t.TempDir(), "test", os.Getpid())
	rec.Built = []string{"img:p"}
	// The fake's failure text is not "No such image", so this one fails.
	if err := Remove(context.Background(), dir, rec); err == nil {
		t.Fatal("Remove succeeded with a failing image rm")
	}
	if !isNoSuchImage("Error response from daemon: No such image: img:p\n") {
		t.Error(`"No such image" not treated as removed`)
	}
	if isNoSuchImage("Error response from daemon: No such image: a\nError response from daemon: conflict: image is in use\n") {
		t.Error("another image error hidden by a missing one")
	}
}

func TestRemoveRefusesNamesThatAreNotOurs(t *testing.T) {
	log := fakeDocker(t)
	dir := t.TempDir()
	for _, name := range []string{"megoocolab", "megoocolab-dev", "megoo-e2e"} {
		path := filepath.Join(dir, name+".json")
		if err := os.WriteFile(path, []byte(`{}`), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := Remove(context.Background(), dir, Record{Project: name, PID: 1}); err == nil {
			t.Errorf("Remove(%s) succeeded", name)
		}
		if !exists(path) {
			t.Errorf("Remove(%s) deleted %s", name, path)
		}
	}
	if got := calls(t, log); len(got) != 0 {
		t.Errorf("docker called for projects that are not ours: %q", got)
	}
}

func TestCleanWorktreeRemovesOnlyThatWorktree(t *testing.T) {
	log := fakeDocker(t)
	dir := t.TempDir()
	a := recordOnDisk(t, dir, t.TempDir(), "test", os.Getpid())
	b := recordOnDisk(t, dir, t.TempDir(), "test", os.Getpid())
	if err := CleanWorktree(context.Background(), dir, a.Worktree); err != nil {
		t.Fatalf("CleanWorktree: %v", err)
	}
	got := calls(t, log)
	if len(got) == 0 {
		t.Fatal("no docker call")
	}
	for _, c := range got {
		if strings.Contains(strings.Join(c, " "), b.Project) {
			t.Errorf("call touches the other worktree: %q", c)
		}
	}
	if exists(filepath.Join(dir, a.Project+".json")) {
		t.Error("A's record left")
	}
	if !exists(filepath.Join(dir, b.Project+".json")) {
		t.Error("B's record removed")
	}
}

func TestSweepRemovesOnlyDeadRecords(t *testing.T) {
	log := fakeDocker(t)
	stubAlive(t, func(pid int) bool { return pid == 2222 })
	dir := t.TempDir()
	dead := recordOnDisk(t, dir, t.TempDir(), "test", 1111)
	live := recordOnDisk(t, dir, t.TempDir(), "test", 2222)
	logs := filepath.Join(dir, "logs")
	if err := os.MkdirAll(logs, 0o700); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	oldLog, newLog := filepath.Join(logs, "old.log"), filepath.Join(logs, "new.log")
	for path, age := range map[string]time.Duration{oldLog: 8 * 24 * time.Hour, newLog: 24 * time.Hour} {
		if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Chtimes(path, now.Add(-age), now.Add(-age)); err != nil {
			t.Fatal(err)
		}
	}
	if err := Sweep(context.Background(), dir, now); err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	got := calls(t, log)
	if len(got) == 0 || !slices.Contains(got[0], dead.Project) {
		t.Errorf("dead set not removed: %q", got)
	}
	for _, c := range got {
		if slices.ContainsFunc(c, func(a string) bool { return strings.Contains(a, live.Project) }) {
			t.Errorf("call touches the live set: %q", c)
		}
	}
	if exists(filepath.Join(dir, dead.Project+".json")) || !exists(filepath.Join(dir, live.Project+".json")) {
		t.Error("wrong records left after Sweep")
	}
	if exists(oldLog) || !exists(newLog) {
		t.Error("Sweep did not delete only the logs older than 7 days")
	}
}

func TestSweepKeepsGoingAfterAFailure(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("FAKEDOCKER_FAIL", "down")
	stubAlive(t, func(int) bool { return false })
	dir := t.TempDir()
	a := recordOnDisk(t, dir, t.TempDir(), "test", 1111)
	b := recordOnDisk(t, dir, t.TempDir(), "test", 1111)
	if err := Sweep(context.Background(), dir, time.Now()); err == nil {
		t.Fatal("Sweep succeeded with failing removals")
	}
	var downs int
	for _, c := range calls(t, log) {
		if slices.Contains(c, "down") && (slices.Contains(c, a.Project) || slices.Contains(c, b.Project)) {
			downs++
		}
	}
	if downs != 2 {
		t.Errorf("Sweep tried %d removals, want 2", downs)
	}
}
