package services

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func testRecord(t *testing.T, worktree, set string, pid int) Record {
	t.Helper()
	return Record{
		Project:  ProjectName(worktree, set),
		Worktree: Canonical(worktree),
		Set:      set,
		PID:      pid,
		Started:  time.Now().UTC().Truncate(time.Second),
	}
}

func TestDirUsesTheEnvironment(t *testing.T) {
	t.Setenv("MEGOO_SERVICES_DIR", "x")
	if got, err := Dir(); err != nil || got != "x" {
		t.Errorf("Dir() = %q, %v; want x", got, err)
	}
	t.Setenv("MEGOO_SERVICES_DIR", "")
	got, err := Dir()
	if err != nil {
		t.Fatalf("Dir: %v", err)
	}
	if want := filepath.Join("megoocolab", "services"); !strings.HasSuffix(got, want) {
		t.Errorf("Dir() = %q, want it to end with %q", got, want)
	}
}

func TestClaimRefusesALiveRecord(t *testing.T) {
	dir := t.TempDir()
	rec := testRecord(t, t.TempDir(), "test", os.Getpid())
	if err := Claim(dir, rec); err != nil {
		t.Fatalf("Claim: %v", err)
	}
	info, err := os.Stat(filepath.Join(dir, rec.Project+".json"))
	if err != nil {
		t.Fatalf("record not written: %v", err)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm() != 0o600 {
		t.Errorf("record mode = %v, want 0600", info.Mode().Perm())
	}
	if err := Claim(dir, rec); !errors.Is(err, ErrBusy) {
		t.Errorf("second Claim = %v, want ErrBusy", err)
	}
	got, err := List(dir)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(got) != 1 || got[0].Project != rec.Project || got[0].PID != rec.PID || !got[0].Started.Equal(rec.Started) {
		t.Errorf("List = %+v, want [%+v]", got, rec)
	}
}

func TestClaimReportsADeadRecord(t *testing.T) {
	dir := t.TempDir()
	rec := testRecord(t, t.TempDir(), "test", 1111)
	stubAlive(t, func(int) bool { return false })
	if err := Claim(dir, rec); err != nil {
		t.Fatalf("Claim: %v", err)
	}
	err := Claim(dir, rec)
	if err == nil || errors.Is(err, ErrBusy) || !strings.Contains(err.Error(), "an earlier check's services could not be removed") {
		t.Errorf("Claim over a dead record = %v", err)
	}
}

func TestSaveReplacesTheRecord(t *testing.T) {
	dir := t.TempDir()
	rec := testRecord(t, t.TempDir(), "test", os.Getpid())
	if err := Claim(dir, rec); err != nil {
		t.Fatalf("Claim: %v", err)
	}
	rec.Built = []string{"img:p"}
	if err := Save(dir, rec); err != nil {
		t.Fatalf("Save: %v", err)
	}
	got, err := List(dir)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(got) != 1 || len(got[0].Built) != 1 || got[0].Built[0] != "img:p" {
		t.Errorf("List after Save = %+v", got)
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 {
		t.Errorf("files after Save = %v, want only the record", entries)
	}
}

func TestListSkipsForeignFiles(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "megoocolab-dev.json"), []byte(`{"project":"megoocolab-dev","pid":1}`), 0o600); err != nil {
		t.Fatal(err)
	}
	wt := t.TempDir()
	other := ProjectName(wt, "e2e")
	if err := os.WriteFile(filepath.Join(dir, ProjectName(wt, "test")+".json"), []byte(`{"project":"`+other+`","pid":1}`), 0o600); err != nil {
		t.Fatal(err)
	}
	rec := testRecord(t, wt, "migrate", os.Getpid())
	if err := Claim(dir, rec); err != nil {
		t.Fatalf("Claim: %v", err)
	}
	got, err := List(dir)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(got) != 1 || got[0].Project != rec.Project {
		t.Errorf("List = %+v, want only %s", got, rec.Project)
	}
}

func TestListOfAMissingFolderIsEmpty(t *testing.T) {
	got, err := List(filepath.Join(t.TempDir(), "none"))
	if err != nil || len(got) != 0 {
		t.Errorf("List(missing) = %v, %v", got, err)
	}
}

func TestAliveSelf(t *testing.T) {
	if !alive(os.Getpid()) {
		t.Error("alive(self) = false")
	}
	cmd := exec.Command("go", "version")
	if err := cmd.Run(); err != nil {
		t.Fatalf("go version: %v", err)
	}
	if alive(cmd.Process.Pid) {
		t.Errorf("alive(%d) = true for a finished process", cmd.Process.Pid)
	}
	if alive(0) || alive(-1) {
		t.Error("alive(0 or -1) = true")
	}
}

// stubAlive replaces processAlive for one test.
func stubAlive(t *testing.T, f func(int) bool) {
	t.Helper()
	old := processAlive
	processAlive = f
	t.Cleanup(func() { processAlive = old })
}
