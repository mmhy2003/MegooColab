package gitstate

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func deref(s *string) string {
	if s == nil {
		return "<nil>"
	}
	return *s
}

// linked returns a bound repo, a linked worktree of it on a new branch, and the
// worktree pinned and captured before anything runs.
func linked(t *testing.T, branch string) (main, wt string, before Snapshot) {
	t.Helper()
	main = repo(t)
	wt = filepath.Join(t.TempDir(), "wt")
	run(t, main, "worktree", "add", "-q", "-b", branch, wt)
	if err := Pin(wt, main); err != nil {
		t.Fatal(err)
	}
	var err error
	if before, err = Capture(wt); err != nil {
		t.Fatal(err)
	}
	return
}

func agentCommit(t *testing.T, wt string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(wt, "evil.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, wt, "add", ".")
	run(t, wt, "commit", "-q", "-m", "agent commit")
}

// craftedRepo is a clone of main whose worktree admin dir points back at
// wt/.git, with branch at head: what an agent can build to be taken for wt's
// repository.
func craftedRepo(t *testing.T, main, wt, branch, head string) (admin string) {
	t.Helper()
	evil := filepath.Join(t.TempDir(), "evil")
	run(t, main, "clone", "-q", main, evil)
	run(t, evil, "branch", branch, head)
	run(t, evil, "worktree", "add", "-q", filepath.Join(evil, "tmpwt"), branch)
	admin = filepath.Join(evil, ".git", "worktrees", "tmpwt")
	if err := os.WriteFile(filepath.Join(admin, "gitdir"), []byte(filepath.ToSlash(filepath.Join(wt, ".git"))+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return admin
}

func TestPinSurvivesRealAdminDirBeingReplaced(t *testing.T) {
	main, wt, before := linked(t, "wtb")
	realAdmin := run(t, wt, "rev-parse", "--absolute-git-dir")
	agentCommit(t, wt)
	if err := os.Remove(filepath.Join(wt, "evil.txt")); err != nil {
		t.Fatal(err)
	}
	admin := craftedRepo(t, main, wt, "wtb", *before.State.Head)
	if err := os.WriteFile(filepath.Join(wt, ".git"), []byte("gitdir: "+filepath.ToSlash(admin)+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.RemoveAll(realAdmin); err != nil {
		t.Fatal(err)
	}
	st, err := CaptureAfter(wt, &before)
	if err == nil || !st.Dirty {
		t.Fatalf("must fail closed: %+v %v", st, err)
	}
}

func TestPinIsDerivedFromTheBoundRepoNotFromDotGit(t *testing.T) {
	main := repo(t)
	wt := filepath.Join(t.TempDir(), "wt")
	run(t, main, "worktree", "add", "-q", "-b", "wtc", wt)
	admin := craftedRepo(t, main, wt, "wtc", run(t, wt, "rev-parse", "HEAD"))
	if err := os.WriteFile(filepath.Join(wt, ".git"), []byte("gitdir: "+filepath.ToSlash(admin)+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := Pin(wt, main); err == nil {
		t.Fatal("a .git file that does not point at the worktree's admin dir must be refused")
	}
}

func TestRewrittenCommondirCannotRedirectTheCapture(t *testing.T) {
	main, wt, before := linked(t, "wtd")
	realAdmin := run(t, wt, "rev-parse", "--absolute-git-dir")
	agentCommit(t, wt)
	run(t, wt, "rm", "-q", "--cached", "evil.txt")
	os.Remove(filepath.Join(wt, "evil.txt"))
	run(t, wt, "read-tree", *before.State.Head)
	evil := filepath.Join(t.TempDir(), "evil3")
	run(t, main, "clone", "-q", "--bare", main, evil)
	run(t, evil, "branch", "-f", "wtd", *before.State.Head)
	if err := os.WriteFile(filepath.Join(realAdmin, "commondir"), []byte(filepath.ToSlash(evil)+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	st, err := CaptureAfter(wt, &before)
	if err == nil || !st.Dirty {
		t.Fatalf("must fail closed: head=%s %+v %v", deref(st.Head), st, err)
	}
}

func TestRewrittenAdminBackPointerFailsClosed(t *testing.T) {
	_, wt, before := linked(t, "wtf")
	admin := run(t, wt, "rev-parse", "--absolute-git-dir")
	if err := os.WriteFile(filepath.Join(admin, "gitdir"), []byte("/nowhere/.git\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	st, err := CaptureAfter(wt, &before)
	if err == nil || !st.Dirty {
		t.Fatalf("must fail closed: %+v %v", st, err)
	}
}

func TestCommitThenDetachBackIsDirty(t *testing.T) {
	_, wt, before := linked(t, "wte")
	agentCommit(t, wt)
	run(t, wt, "checkout", "-q", "--detach", *before.State.Head)
	st, err := CaptureAfter(wt, &before)
	if err != nil || !st.Dirty {
		t.Fatalf("head=%s dirty=%v err=%v", deref(st.Head), st.Dirty, err)
	}
}

func TestCommitThenSwitchBranchIsDirty(t *testing.T) {
	_, wt, before := linked(t, "wtg")
	agentCommit(t, wt)
	run(t, wt, "checkout", "-q", "-b", "other", *before.State.Head)
	st, err := CaptureAfter(wt, &before)
	if err != nil || !st.Dirty {
		t.Fatalf("dirty=%v err=%v", st.Dirty, err)
	}
}

func TestAPlainCommitOnTheBranchIsNotDirtyByItself(t *testing.T) {
	_, wt, before := linked(t, "wth")
	agentCommit(t, wt)
	st, err := CaptureAfter(wt, &before)
	if err != nil || st.Dirty || *st.Head == *before.State.Head {
		t.Fatalf("head moved and is visible to the server, dirty stays false: %+v %v", st, err)
	}
}

func TestVerbSkipsOptionValues(t *testing.T) {
	if v := verb([]string{"-c", "core.x=y", "-C", "/p", "--git-dir=/g", "status"}); v != "status" {
		t.Fatalf("verb = %q", v)
	}
}

// Index rewrites inside a nested repository (a status refresh) are not edits.
func TestNestedRepoGitDirIsStampedNotHashed(t *testing.T) {
	dir := repo(t)
	sub := filepath.Join(dir, "sub")
	run(t, dir, "init", "-q", "sub")
	f := filepath.Join(sub, "f.txt")
	if err := os.WriteFile(f, []byte("one"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, sub, "add", "f.txt")
	run(t, sub, "commit", "-q", "-m", "c")
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	later := time.Now().Add(time.Minute)
	if err := os.Chtimes(f, later, later); err != nil {
		t.Fatal(err)
	}
	run(t, sub, "status", "--porcelain") // rewrites sub/.git/index with the new stat data
	st, err := CaptureAfter(dir, &before)
	if err != nil || st.Dirty {
		t.Fatalf("an index refresh is not an edit: dirty=%v err=%v", st.Dirty, err)
	}
	// a new file in the nested .git is
	if err := os.WriteFile(filepath.Join(sub, ".git", "planted"), []byte("p"), 0o644); err != nil {
		t.Fatal(err)
	}
	st, err = CaptureAfter(dir, &before)
	if err != nil || !st.Dirty {
		t.Fatalf("planted file: dirty=%v err=%v", st.Dirty, err)
	}
}
