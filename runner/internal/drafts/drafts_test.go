package drafts

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const draftID = "0b7c1e52-4f3a-4c3e-9d55-6a0f2e1b9c11"

func runGit(t *testing.T, dir string, args ...string) string {
	t.Helper()
	out, err := exec.Command("git", append([]string{"-C", dir}, args...)...).CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

func newRepo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	runGit(t, dir, "init", "-q")
	runGit(t, dir, "config", "user.name", "T")
	runGit(t, dir, "config", "user.email", "t@example.com")
	runGit(t, dir, "config", "commit.gpgsign", "false")
	if err := os.WriteFile(filepath.Join(dir, "a.txt"), []byte("a"), 0o644); err != nil {
		t.Fatal(err)
	}
	runGit(t, dir, "add", ".")
	runGit(t, dir, "commit", "-q", "-m", "init")
	return dir
}

func TestEnsureEmptyFolderPersistsAcrossCalls(t *testing.T) {
	cache := t.TempDir()
	dir, err := Ensure(context.Background(), cache, "agent-1", draftID, "")
	if err != nil {
		t.Fatal(err)
	}
	if want := filepath.Join(cache, "drafts", "agent-1", draftID); dir != want {
		t.Fatalf("dir = %s, want %s", dir, want)
	}
	if err := os.WriteFile(filepath.Join(dir, "notes.md"), []byte("kept"), 0o644); err != nil {
		t.Fatal(err)
	}
	again, err := Ensure(context.Background(), cache, "agent-1", draftID, "")
	if err != nil || again != dir {
		t.Fatalf("again = %s, %v", again, err)
	}
	if _, err := os.Stat(filepath.Join(dir, "notes.md")); err != nil {
		t.Fatalf("the folder was not kept: %v", err)
	}
}

func TestEnsureProjectDraftIsDetachedWorktree(t *testing.T) {
	cache, repo := t.TempDir(), newRepo(t)
	branchesBefore := runGit(t, repo, "branch", "--list")
	dir, err := Ensure(context.Background(), cache, "agent-1", draftID, repo)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "a.txt")); err != nil {
		t.Fatalf("the worktree has no checkout: %v", err)
	}
	if err := exec.Command("git", "-C", dir, "symbolic-ref", "-q", "HEAD").Run(); err == nil {
		t.Fatal("HEAD is on a branch, want detached")
	}
	if got := runGit(t, repo, "branch", "--list"); got != branchesBefore {
		t.Fatalf("branches changed: %q -> %q", branchesBefore, got)
	}
	again, err := Ensure(context.Background(), cache, "agent-1", draftID, repo)
	if err != nil || again != dir {
		t.Fatalf("again = %s, %v", again, err)
	}
}

func TestRemoveDropsWorktreeRegistration(t *testing.T) {
	cache, repo := t.TempDir(), newRepo(t)
	dir, err := Ensure(context.Background(), cache, "agent-1", draftID, repo)
	if err != nil {
		t.Fatal(err)
	}
	if err := Remove(cache, "agent-1", draftID); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatalf("the folder is still there: %v", err)
	}
	if list := runGit(t, repo, "worktree", "list", "--porcelain"); strings.Contains(list, draftID) {
		t.Fatalf("the worktree is still registered:\n%s", list)
	}
	if err := Remove(cache, "agent-1", draftID); err != nil {
		t.Fatalf("removing twice: %v", err)
	}
}

func TestSweepRemovesOnlyOldFolders(t *testing.T) {
	cache := t.TempDir()
	const other = "1c2d3e4f-0000-4000-8000-000000000000"
	oldDir, _ := Ensure(context.Background(), cache, "agent-1", draftID, "")
	newDir, _ := Ensure(context.Background(), cache, "agent-1", other, "")
	now := time.Now()
	old := now.Add(-31 * 24 * time.Hour)
	if err := os.Chtimes(metaPath(cache, "agent-1", draftID), old, old); err != nil {
		t.Fatal(err)
	}
	if errs := Sweep(cache, SweepAge, now); len(errs) != 0 {
		t.Fatal(errs)
	}
	if _, err := os.Stat(oldDir); !os.IsNotExist(err) {
		t.Fatalf("the old folder is still there: %v", err)
	}
	if _, err := os.Stat(newDir); err != nil {
		t.Fatalf("the recent folder went: %v", err)
	}
}

func TestEnsureRejectsUnsafeIDs(t *testing.T) {
	cache := t.TempDir()
	for _, ids := range [][2]string{{"../x", draftID}, {"agent-1", "../../etc"}, {"agent-1", ""}} {
		if _, err := Ensure(context.Background(), cache, ids[0], ids[1], ""); err == nil {
			t.Errorf("Ensure(%q, %q) = nil error", ids[0], ids[1])
		}
	}
}
