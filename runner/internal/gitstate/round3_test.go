package gitstate

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestUnpinnedWorktreeIsAnErrorInProduction(t *testing.T) {
	dir := repo(t)
	allowImplicitPin = false
	defer func() { allowImplicitPin = true }()
	if _, err := Capture(dir); err == nil {
		t.Fatal("a worktree nobody pinned must not be read from its own .git")
	}
	if err := Pin(dir, dir); err != nil {
		t.Fatal(err)
	}
	if _, err := Capture(dir); err != nil {
		t.Fatal(err)
	}
}

func TestTwoAdminEntriesNamingTheWorktreeAreRefused(t *testing.T) {
	main := repo(t)
	wt := filepath.Join(t.TempDir(), "wt")
	run(t, main, "worktree", "add", "-q", "-b", "dup", wt)
	real := run(t, wt, "rev-parse", "--absolute-git-dir")
	dup := filepath.Join(filepath.Dir(real), "zzz-dup")
	if err := os.MkdirAll(dup, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{"gitdir", "commondir", "HEAD"} {
		b, err := os.ReadFile(filepath.Join(real, f))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dup, f), b, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := Pin(wt, main); err == nil {
		t.Fatal("two registrations for one worktree must be refused")
	}
}

func commonOf(t *testing.T, wt string) string {
	t.Helper()
	p, err := pinFor(wt)
	if err != nil {
		t.Fatal(err)
	}
	return p.common
}

func TestCleanFilterAndAttributesAddedDuringTheRunAreDirty(t *testing.T) {
	main := repo(t)
	wt := filepath.Join(t.TempDir(), "wt")
	run(t, main, "worktree", "add", "-q", "-b", "flt", wt)
	if err := os.WriteFile(filepath.Join(wt, "t.txt"), []byte("aaaa\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, wt, "add", "t.txt")
	run(t, wt, "commit", "-q", "-m", "t")
	if err := Pin(wt, main); err != nil {
		t.Fatal(err)
	}
	before, err := Capture(wt)
	if err != nil {
		t.Fatal(err)
	}
	common := commonOf(t, wt)
	run(t, wt, "config", "filter.x.clean", "echo aaaa")
	if err := os.MkdirAll(filepath.Join(common, "info"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(common, "info", "attributes"), []byte("t.txt filter=x\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(wt, "t.txt"), []byte("bbbb\n"), 0o644); err != nil { // same size
		t.Fatal(err)
	}
	st, err := CaptureAfter(wt, &before)
	if err != nil || !st.Dirty {
		t.Fatalf("dirty=%v err=%v", st.Dirty, err)
	}
}

func TestEachHiddenGitFileChangeIsDirty(t *testing.T) {
	for name, change := range map[string]func(t *testing.T, wt, common, admin string){
		"config":          func(t *testing.T, wt, c, a string) { run(t, wt, "config", "some.key", "v") },
		"info/attributes": func(t *testing.T, wt, c, a string) { writeIn(t, filepath.Join(c, "info"), "attributes", "* -diff\n") },
		"info/exclude":    func(t *testing.T, wt, c, a string) { writeIn(t, filepath.Join(c, "info"), "exclude", "/secret\n") },
		"config.worktree": func(t *testing.T, wt, c, a string) { writeIn(t, a, "config.worktree", "[some]\n\tkey = v\n") },
	} {
		t.Run(name, func(t *testing.T) {
			main := repo(t)
			wt := filepath.Join(t.TempDir(), "wt")
			run(t, main, "worktree", "add", "-q", "-b", "hid", wt)
			if err := Pin(wt, main); err != nil {
				t.Fatal(err)
			}
			before, err := Capture(wt)
			if err != nil {
				t.Fatal(err)
			}
			st, err := CaptureAfter(wt, &before)
			if err != nil || st.Dirty {
				t.Fatalf("untouched: dirty=%v err=%v", st.Dirty, err)
			}
			p, _ := pinFor(wt)
			change(t, wt, p.common, p.gitdir)
			st, err = CaptureAfter(wt, &before)
			if err != nil || !st.Dirty {
				t.Fatalf("dirty=%v err=%v", st.Dirty, err)
			}
		})
	}
}

func writeIn(t *testing.T, dir, name, content string) {
	t.Helper()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

// A clean filter that was already configured when the run started is not a
// change, but it must neither run inside the capture nor hide an edit.
func TestConfiguredFilterNeverRunsAndCannotHideAnEdit(t *testing.T) {
	dir := repo(t)
	marker := filepath.Join(t.TempDir(), "ran")
	run(t, dir, "config", "filter.x.clean", "touch "+filepath.ToSlash(marker)+"; cat")
	writeIn(t, filepath.Join(dir, ".git", "info"), "attributes", "a.txt filter=x\n")
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "a.txt"), []byte("b\n"), 0o644); err != nil { // same size as "a\n"
		t.Fatal(err)
	}
	st, err := CaptureAfter(dir, &before)
	if err != nil || !st.Dirty {
		t.Fatalf("dirty=%v err=%v", st.Dirty, err)
	}
	if _, err := os.Stat(marker); err == nil {
		t.Fatal("the agent's clean filter ran inside the capture")
	}
	_ = strings.TrimSpace
}
