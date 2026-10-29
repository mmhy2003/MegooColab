package worktree

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// hangingCheckoutRepo is a repo whose a.txt goes through a smudge filter that
// hangs (the test binary, see TestMain), so `git worktree add` stalls in the
// middle of its checkout, as a huge repo or a slow antivirus would make it.
// unhang makes the filter a pass-through again.
func hangingCheckoutRepo(t *testing.T) (repo string, unhang func()) {
	t.Helper()
	repo = newRepo(t)
	if err := os.WriteFile(filepath.Join(repo, ".gitattributes"), []byte("a.txt filter=hang\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	runGit(t, repo, "add", ".gitattributes")
	runGit(t, repo, "commit", "-q", "-m", "attrs")
	runGit(t, repo, "config", "filter.hang.smudge", `"`+filepath.ToSlash(os.Args[0])+`"`)
	t.Setenv("WORKTREE_HANG_SMUDGE", "1")
	return repo, func() { runGit(t, repo, "config", "--unset", "filter.hang.smudge") }
}

func withAddTimeout(t *testing.T, d time.Duration) {
	t.Helper()
	old := addTimeout
	addTimeout = d
	t.Cleanup(func() { addTimeout = old })
}

func registered(t *testing.T, repo, path string) bool {
	t.Helper()
	ok, _, err := worktreeEntry(repo, path)
	if err != nil {
		t.Fatal(err)
	}
	return ok
}

// assertNothingLeft checks a failed Ensure left nothing behind: no registration, no
// directory, no admin directory.
func assertNothingLeft(t *testing.T, repo, path string) {
	t.Helper()
	if registered(t, repo, path) {
		t.Errorf("%s is still a registered worktree:\n%s", path, runGit(t, repo, "worktree", "list", "--porcelain"))
	}
	if _, err := os.Stat(path); err == nil {
		t.Errorf("%s was left behind", path)
	}
	if ents, _ := os.ReadDir(filepath.Join(repo, ".git", "worktrees")); len(ents) != 0 {
		t.Errorf("admin directories left behind: %v", ents)
	}
}

func assertComplete(t *testing.T, path, branch string) {
	t.Helper()
	if b, err := os.ReadFile(filepath.Join(path, "a.txt")); err != nil || strings.TrimSpace(string(b)) != "a" {
		t.Fatalf("a.txt = %q, %v", b, err)
	}
	if got := runGit(t, path, "rev-parse", "--abbrev-ref", "HEAD"); got != branch {
		t.Fatalf("HEAD = %q, want %q", got, branch)
	}
	if st := runGit(t, path, "status", "--porcelain"); st != "" {
		t.Fatalf("fresh worktree is dirty:\n%s", st)
	}
	if out := runGit(t, path, "worktree", "list", "--porcelain"); strings.Contains(out, "locked") {
		t.Fatalf("worktree still locked:\n%s", out)
	}
}

func TestEnsureCleansUpWhenAddTimesOut(t *testing.T) {
	repo, unhang := hangingCheckoutRepo(t)
	cache := t.TempDir()
	withAddTimeout(t, 3*time.Second)
	path := filepath.Join(cache, "worktrees", "agent-1", "MEG-1")

	start := time.Now()
	if _, _, err := Ensure(context.Background(), io.Discard, repo, cache, "agent-1", "MEG-1", "Title"); err == nil {
		t.Fatal("a checkout that outlasts the add timeout must fail Ensure")
	}
	if d := time.Since(start); d > 30*time.Second {
		t.Fatalf("Ensure took %v", d)
	}
	assertNothingLeft(t, repo, path)

	unhang()
	p, branch, err := Ensure(context.Background(), io.Discard, repo, cache, "agent-1", "MEG-1", "Title")
	if err != nil {
		t.Fatalf("retry: %v", err)
	}
	if p != path {
		t.Fatalf("path = %q", p)
	}
	assertComplete(t, p, branch)
}

func TestEnsureCleansUpWhenCancelledDuringAdd(t *testing.T) {
	repo, unhang := hangingCheckoutRepo(t)
	cache := t.TempDir()
	withAddTimeout(t, 5*time.Minute)
	started := filepath.Join(t.TempDir(), "started")
	t.Setenv("WORKTREE_SMUDGE_STARTED", started)
	path := filepath.Join(cache, "worktrees", "agent-1", "MEG-2")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() {
		for i := 0; i < 600; i++ {
			if _, err := os.Stat(started); err == nil {
				break
			}
			time.Sleep(50 * time.Millisecond)
		}
		cancel()
	}()
	start := time.Now()
	_, _, err := Ensure(ctx, io.Discard, repo, cache, "agent-1", "MEG-2", "Title")
	if err == nil {
		t.Fatal("a cancelled add must fail Ensure")
	}
	if !strings.Contains(err.Error(), "cancel") {
		t.Errorf("error does not say it was cancelled: %v", err)
	}
	if d := time.Since(start); d > time.Minute {
		t.Fatalf("Ensure took %v", d)
	}
	if _, err := os.Stat(started); err != nil {
		t.Fatal("the checkout never started; the test did not exercise a stalled add")
	}
	assertNothingLeft(t, repo, path)

	unhang()
	p, branch, err := Ensure(context.Background(), io.Discard, repo, cache, "agent-1", "MEG-2", "Title")
	if err != nil {
		t.Fatalf("retry: %v", err)
	}
	assertComplete(t, p, branch)
}

// adminDir is the worktree's directory under <git-common-dir>/worktrees/.
func adminDir(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(path, ".git"))
	if err != nil {
		t.Fatal(err)
	}
	return strings.TrimSpace(strings.TrimPrefix(string(b), "gitdir:"))
}

func TestEnsureRecreatesAWorktreeLeftInitializing(t *testing.T) {
	repo, cache := newRepo(t), t.TempDir()
	path, branch, err := Ensure(context.Background(), io.Discard, repo, cache, "agent-1", "MEG-3", "Title")
	if err != nil {
		t.Fatal(err)
	}
	// What an add killed mid-checkout leaves: git's "initializing" lock and
	// files that were never written.
	if err := os.WriteFile(filepath.Join(adminDir(t, path), "locked"), []byte("initializing"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(path, "a.txt")); err != nil {
		t.Fatal(err)
	}
	p, b, err := Ensure(context.Background(), io.Discard, repo, cache, "agent-1", "MEG-3", "Title")
	if err != nil {
		t.Fatalf("Ensure: %v", err)
	}
	if p != path || b != branch {
		t.Fatalf("got %q %q", p, b)
	}
	assertComplete(t, p, b)
}

func TestEnsureRecreatesAWorktreeWithoutHEAD(t *testing.T) {
	repo, cache := newRepo(t), t.TempDir()
	path, _, err := Ensure(context.Background(), io.Discard, repo, cache, "agent-1", "MEG-4", "Title")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(adminDir(t, path), "HEAD")); err != nil {
		t.Fatal(err)
	}
	p, b, err := Ensure(context.Background(), io.Discard, repo, cache, "agent-1", "MEG-4", "Title")
	if err != nil {
		t.Fatalf("Ensure: %v", err)
	}
	assertComplete(t, p, b)
}

func TestEnsureReusesAHealthyWorktreeAsIs(t *testing.T) {
	repo, cache := newRepo(t), t.TempDir()
	path, _, err := Ensure(context.Background(), io.Discard, repo, cache, "agent-1", "MEG-5", "Title")
	if err != nil {
		t.Fatal(err)
	}
	// The agent's work in progress, and a lock someone else took on purpose:
	// neither makes the worktree broken.
	work := filepath.Join(path, "work.txt")
	if err := os.WriteFile(work, []byte("wip"), 0o644); err != nil {
		t.Fatal(err)
	}
	runGit(t, repo, "worktree", "lock", "--reason", "keep me", path)
	p, _, err := Ensure(context.Background(), io.Discard, repo, cache, "agent-1", "MEG-5", "Title")
	if err != nil || p != path {
		t.Fatalf("reuse = %q %v", p, err)
	}
	if b, err := os.ReadFile(work); err != nil || string(b) != "wip" {
		t.Fatalf("work in progress lost: %q %v", b, err)
	}
}

func TestEnsureRepairsAMissingOrGarbledGitFileAndKeepsTheWork(t *testing.T) {
	for name, damage := range map[string]func(path string) error{
		"missing": func(path string) error { return os.Remove(filepath.Join(path, ".git")) },
		"garbled": func(path string) error { return os.WriteFile(filepath.Join(path, ".git"), []byte("nonsense"), 0o644) },
	} {
		t.Run(name, func(t *testing.T) {
			repo, cache := newRepo(t), t.TempDir()
			path, branch, err := Ensure(context.Background(), io.Discard, repo, cache, "agent-1", "MEG-6", "Title")
			if err != nil {
				t.Fatal(err)
			}
			work := filepath.Join(path, "work.txt")
			if err := os.WriteFile(work, []byte("wip"), 0o644); err != nil {
				t.Fatal(err)
			}
			if err := damage(path); err != nil {
				t.Fatal(err)
			}
			var log strings.Builder
			p, b, err := Ensure(context.Background(), &log, repo, cache, "agent-1", "MEG-6", "Title")
			if err != nil || p != path || b != branch {
				t.Fatalf("Ensure = %q %q %v", p, b, err)
			}
			if got, err := os.ReadFile(work); err != nil || string(got) != "wip" {
				t.Fatalf("uncommitted work lost: %q %v\n%s", got, err, log.String())
			}
			if got := runGit(t, path, "rev-parse", "--abbrev-ref", "HEAD"); got != branch {
				t.Fatalf("HEAD = %q", got)
			}
			if !strings.Contains(log.String(), "repaired") {
				t.Fatalf("log = %q", log.String())
			}
		})
	}
}
