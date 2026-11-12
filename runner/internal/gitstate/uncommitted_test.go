package gitstate

import (
	"os"
	"path/filepath"
	"testing"
)

// Uncommitted is the worktree as `git status` shows it when the run ends: changes nobody committed. Dirty is
// broader (anything the run changed, ignored files included), so a run that committed its work but made or removed
// ignored files (a __pycache__) is dirty and has nothing uncommitted.
func TestUncommittedIsWhatStatusShowsAtTheEnd(t *testing.T) {
	write := func(t *testing.T, dir, name, content string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(filepath.Join(dir, name)), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	ignoring := func(t *testing.T) string {
		dir := repo(t)
		write(t, dir, ".gitignore", "__pycache__/\n")
		run(t, dir, "add", ".")
		run(t, dir, "commit", "-q", "-m", "ignore")
		return dir
	}
	after := func(t *testing.T, dir string, before Snapshot) (dirty, uncommitted bool) {
		t.Helper()
		st, err := CaptureAfter(dir, &before)
		if err != nil {
			t.Fatal(err)
		}
		if st.Uncommitted == nil {
			t.Fatal("uncommitted not reported")
		}
		return st.Dirty, *st.Uncommitted
	}

	t.Run("committed work that made ignored files", func(t *testing.T) {
		dir := ignoring(t)
		before, _ := Capture(dir)
		write(t, dir, "b.py", "b\n")
		run(t, dir, "add", ".")
		run(t, dir, "commit", "-q", "-m", "step")
		write(t, dir, "__pycache__/b.pyc", "x")
		if dirty, uncommitted := after(t, dir, before); !dirty || uncommitted {
			t.Fatalf("dirty=%v uncommitted=%v, want dirty and nothing uncommitted", dirty, uncommitted)
		}
	})
	t.Run("a run that only removed ignored files", func(t *testing.T) {
		dir := ignoring(t)
		write(t, dir, "__pycache__/b.pyc", "x")
		before, _ := Capture(dir)
		if err := os.RemoveAll(filepath.Join(dir, "__pycache__")); err != nil {
			t.Fatal(err)
		}
		if dirty, uncommitted := after(t, dir, before); !dirty || uncommitted {
			t.Fatalf("dirty=%v uncommitted=%v, want dirty and nothing uncommitted", dirty, uncommitted)
		}
	})
	t.Run("an edit left uncommitted", func(t *testing.T) {
		dir := ignoring(t)
		before, _ := Capture(dir)
		write(t, dir, "a.txt", "changed\n")
		if _, uncommitted := after(t, dir, before); !uncommitted {
			t.Fatal("an uncommitted edit must count")
		}
	})
	t.Run("a new file left uncommitted, even one an earlier run made", func(t *testing.T) {
		dir := ignoring(t)
		write(t, dir, "new.txt", "n\n")
		before, _ := Capture(dir)
		if dirty, uncommitted := after(t, dir, before); dirty || !uncommitted {
			t.Fatalf("dirty=%v uncommitted=%v, want not dirty (not this run's) but uncommitted", dirty, uncommitted)
		}
	})
	t.Run("MegooColab's own files never count", func(t *testing.T) {
		dir := ignoring(t)
		before, _ := Capture(dir)
		write(t, dir, ".megoocolab/plan.md", "p\n")
		if _, uncommitted := after(t, dir, before); uncommitted {
			t.Fatal(".megoocolab/ must not count as uncommitted")
		}
	})
}
