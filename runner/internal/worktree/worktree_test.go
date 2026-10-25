package worktree

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

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

func TestSlug(t *testing.T) {
	long := strings.Repeat("ab ", 30)
	cases := map[string]string{
		"Sync Orders w/ ERP!":   "sync-orders-w-erp",
		"":                      "task",
		"!!!":                   "task",
		"  Hello   World  ":     "hello-world",
		strings.Repeat("a", 50): strings.Repeat("a", 40),
		"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa b": strings.Repeat("a", 39),
	}
	for in, want := range cases {
		if got := Slug(in); got != want {
			t.Errorf("Slug(%q) = %q, want %q", in, got, want)
		}
	}
	if got := Slug(long); len(got) > 40 || strings.HasSuffix(got, "-") {
		t.Errorf("Slug(long) = %q", got)
	}
}

func TestEnsureCreatesThenReuses(t *testing.T) {
	repo, cache := newRepo(t), t.TempDir()
	path, branch, err := Ensure(repo, cache, "agent1", "MEG-7", "Sync Orders w/ ERP!")
	if err != nil {
		t.Fatal(err)
	}
	if branch != "megoo/MEG-7-sync-orders-w-erp" {
		t.Fatalf("branch = %q", branch)
	}
	if want := filepath.Join(cache, "worktrees", "agent1", "MEG-7"); path != want {
		t.Fatalf("path = %q, want %q", path, want)
	}
	if _, err := os.Stat(filepath.Join(path, "a.txt")); err != nil {
		t.Fatalf("worktree not populated: %v", err)
	}
	if got := runGit(t, path, "rev-parse", "--abbrev-ref", "HEAD"); got != branch {
		t.Fatalf("HEAD = %q", got)
	}
	p2, b2, err := Ensure(repo, cache, "agent1", "MEG-7", "Sync Orders w/ ERP!")
	if err != nil || p2 != path || b2 != branch {
		t.Fatalf("reuse = %q %q %v", p2, b2, err)
	}
}

func TestEnsureExistingBranchWithoutWorktree(t *testing.T) {
	repo, cache := newRepo(t), t.TempDir()
	runGit(t, repo, "branch", "megoo/MEG-8-x")
	path, branch, err := Ensure(repo, cache, "a", "MEG-8", "x")
	if err != nil {
		t.Fatal(err)
	}
	if got := runGit(t, path, "rev-parse", "--abbrev-ref", "HEAD"); got != branch {
		t.Fatalf("HEAD = %q", got)
	}
}

func TestEnsureRejectsNonRepo(t *testing.T) {
	if _, _, err := Ensure(t.TempDir(), t.TempDir(), "a", "MEG-1", "t"); err == nil {
		t.Fatal("expected error")
	}
}

func TestEnsureRefusesStaleDirectory(t *testing.T) {
	repo, cache := newRepo(t), t.TempDir()
	stale := filepath.Join(cache, "worktrees", "a", "MEG-9")
	if err := os.MkdirAll(stale, 0o755); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(stale, "keep.txt")
	os.WriteFile(marker, []byte("x"), 0o644)
	if _, _, err := Ensure(repo, cache, "a", "MEG-9", "t"); err == nil {
		t.Fatal("expected error")
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatal("stale directory was touched")
	}
}

func TestEnsureRejectsUnsafeIDs(t *testing.T) {
	bad := []string{"", "-x", "..", "../../x", "a/b", `a\b`, filepath.Join(os.TempDir(), "abs"), ".hidden"}
	for _, v := range bad {
		for _, which := range []string{"task", "agent"} {
			repo, cache := newRepo(t), filepath.Join(t.TempDir(), "cache")
			agent, key := "agent1", "MEG-1"
			if which == "task" {
				key = v
			} else {
				agent = v
			}
			if _, _, err := Ensure(repo, cache, agent, key, "t"); err == nil {
				t.Errorf("%s=%q: expected error", which, v)
			}
			if _, err := os.Stat(cache); err == nil {
				t.Errorf("%s=%q: created %s", which, v, cache)
			}
		}
	}
}
