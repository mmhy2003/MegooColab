package gitstate

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestMain(m *testing.M) {
	allowImplicitPin = true
	if os.Getenv("GITSTATE_FAKE_GIT") == "fail-ls-files" {
		os.Exit(fakeGitFailingLsFiles())
	}
	// The test binary doubles as a git that hangs, for the timeout test.
	if os.Getenv("GITSTATE_FAKE_GIT") == "1" {
		time.Sleep(time.Minute)
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func TestReadTimesOutInsteadOfHanging(t *testing.T) {
	dir := repo(t)
	t.Setenv("GITSTATE_FAKE_GIT", "1")
	oldBin, oldTimeout := gitBin, timeout
	gitBin, timeout = os.Args[0], 300*time.Millisecond
	t.Cleanup(func() { gitBin, timeout = oldBin, oldTimeout })

	start := time.Now()
	_, err := Read(dir)
	if err == nil {
		t.Fatal("a hung git must be an error")
	}
	if d := time.Since(start); d > 10*time.Second {
		t.Fatalf("took %v", d)
	}
}

// each way of hiding real changes from `git status` must still end as dirty.
func TestHiddenChangesStillCountAsDirty(t *testing.T) {
	write := func(t *testing.T, dir, name, content string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	cases := map[string]func(t *testing.T, dir string){
		"skip-worktree": func(t *testing.T, dir string) {
			write(t, dir, "a.txt", "changed\n")
			run(t, dir, "update-index", "--skip-worktree", "a.txt")
		},
		"assume-unchanged": func(t *testing.T, dir string) {
			write(t, dir, "a.txt", "changed\n")
			run(t, dir, "update-index", "--assume-unchanged", "a.txt")
		},
		"self-ignoring .gitignore": func(t *testing.T, dir string) {
			write(t, dir, ".gitignore", "*\n")
			write(t, dir, "new.txt", "n\n")
		},
		"info/exclude": func(t *testing.T, dir string) {
			write(t, dir, "new.txt", "n\n")
			f, err := os.OpenFile(filepath.Join(dir, ".git", "info", "exclude"), os.O_APPEND|os.O_WRONLY, 0o644)
			if err != nil {
				t.Fatal(err)
			}
			_, _ = f.WriteString("new.txt\n")
			f.Close()
		},
		"stash": func(t *testing.T, dir string) {
			write(t, dir, "a.txt", "changed\n")
			run(t, dir, "stash")
		},
	}
	for name, hide := range cases {
		t.Run(name, func(t *testing.T) {
			dir := repo(t)
			before, err := Capture(dir)
			if err != nil || before.State.Dirty {
				t.Fatalf("before = %+v, %v", before.State, err)
			}
			hide(t, dir)
			after, err := Capture(dir)
			if err != nil {
				t.Fatal(err)
			}
			if st := After(&before, after); !st.Dirty {
				t.Fatalf("hidden change not reported: %+v", st)
			}
		})
	}
}

func TestUnchangedRepoWithIgnoredFilesIsNotDirty(t *testing.T) {
	dir := repo(t)
	if err := os.WriteFile(filepath.Join(dir, ".gitignore"), []byte("*.log\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, dir, "add", ".gitignore")
	run(t, dir, "commit", "-q", "-m", "ignore")
	if err := os.WriteFile(filepath.Join(dir, "x.log"), []byte("l"), 0o644); err != nil {
		t.Fatal(err)
	}
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	after, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	if st := After(&before, after); st.Dirty {
		t.Fatalf("unchanged repo reported dirty: %+v", st)
	}
	if st := After(nil, after); st.Dirty {
		t.Fatal("no baseline must not invent dirt")
	}
}

func TestStandingSkipWorktreeFlagIsNotDirty(t *testing.T) {
	for _, flag := range []string{"--skip-worktree", "--assume-unchanged"} {
		t.Run(flag, func(t *testing.T) {
			dir := repo(t)
			run(t, dir, "update-index", flag, "a.txt") // standing flag, e.g. a sparse checkout
			before, err := Capture(dir)
			if err != nil {
				t.Fatal(err)
			}
			after, err := Capture(dir)
			if err != nil {
				t.Fatal(err)
			}
			if st := After(&before, after); st.Dirty || before.State.Dirty {
				t.Fatalf("standing flag reported dirty: before %+v after %+v", before.State, st)
			}
		})
	}
}

func TestFlaggingAnotherFileDuringTheRunIsDirty(t *testing.T) {
	dir := repo(t)
	if err := os.WriteFile(filepath.Join(dir, "b.txt"), []byte("b\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, dir, "add", "b.txt")
	run(t, dir, "commit", "-q", "-m", "b")
	run(t, dir, "update-index", "--skip-worktree", "a.txt")
	before, _ := Capture(dir)
	run(t, dir, "update-index", "--skip-worktree", "b.txt")
	after, _ := Capture(dir)
	if st := After(&before, after); !st.Dirty {
		t.Fatal("a newly flagged file must be dirty")
	}
	// a changed flag (skip-worktree to assume-unchanged) counts too
	run(t, dir, "update-index", "--no-skip-worktree", "b.txt")
	run(t, dir, "update-index", "--assume-unchanged", "b.txt")
	third, _ := Capture(dir)
	if st := After(&after, third); !st.Dirty {
		t.Fatal("a changed flag must be dirty")
	}
}

func TestReplacedObjectsCannotHideAnEdit(t *testing.T) {
	dir := repo(t)
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	c1 := run(t, dir, "rev-parse", "HEAD")
	if err := os.WriteFile(filepath.Join(dir, "a.txt"), []byte("edited\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, dir, "commit", "-q", "-a", "-m", "edit")
	c2 := run(t, dir, "rev-parse", "HEAD")
	run(t, dir, "replace", c1, c2) // from now on c1 reads as c2
	run(t, dir, "reset", "-q", "--hard", c1)
	after, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	st := After(&before, after)
	if *st.Head == *before.State.Head && !st.Dirty {
		t.Fatalf("a replaced HEAD hid the edit: %+v", st)
	}
}

func TestStashRefAbsentIsNotAnErrorButFailuresAre(t *testing.T) {
	dir := repo(t)
	if s, err := stashRef(dir); err != nil || s != "" {
		t.Fatalf("absent = %q, %v", s, err)
	}
	if err := os.WriteFile(filepath.Join(dir, "a.txt"), []byte("x\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, dir, "stash")
	if s, err := stashRef(dir); err != nil || s == "" {
		t.Fatalf("present = %q, %v", s, err)
	}
	t.Setenv("GITSTATE_FAKE_GIT", "1")
	restore := OverrideForTest(os.Args[0], 300*time.Millisecond)
	defer restore()
	if _, err := stashRef(dir); err == nil {
		t.Fatal("a timeout is not 'ref absent'")
	}
	if _, err := stashRef(filepath.Join(dir, "no-such-dir")); err == nil {
		t.Fatal("a failing git is not 'ref absent'")
	}
}

// I1: an earlier workspace run (implement, step_fix, final_fix) may leave
// uncommitted edits behind; a read-only run is dirty only for what it changed.
func TestDirtLeftByAnEarlierRunIsNotTheReviewsChange(t *testing.T) {
	write := func(t *testing.T, dir, name, content string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	leftover := func(t *testing.T) (string, Snapshot) {
		t.Helper()
		dir := repo(t)
		write(t, dir, "a.txt", "implementer edit\n") // modified tracked file
		write(t, dir, "notes.txt", "untracked\n")    // untracked file
		if err := os.MkdirAll(filepath.Join(dir, ".megoocolab"), 0o755); err != nil {
			t.Fatal(err)
		}
		write(t, dir, ".megoocolab/plan.md", "plan\n")
		before, err := Capture(dir)
		if err != nil || !before.State.Dirty {
			t.Fatalf("before = %+v, %v", before.State, err)
		}
		return dir, before
	}
	after := func(t *testing.T, dir string, before Snapshot) bool {
		t.Helper()
		snap, err := Capture(dir)
		if err != nil {
			t.Fatal(err)
		}
		return After(&before, snap).Dirty
	}

	t.Run("untouched review", func(t *testing.T) {
		dir, before := leftover(t)
		write(t, dir, ".megoocolab/plan.md", "new plan\n") // MegooColab's own files never count
		if after(t, dir, before) {
			t.Fatal("an untouched review must not be dirty")
		}
	})
	t.Run("review edits the already-modified file", func(t *testing.T) {
		dir, before := leftover(t)
		write(t, dir, "a.txt", "review edit\n")
		if !after(t, dir, before) {
			t.Fatal("editing a dirty tracked file must be dirty")
		}
	})
	t.Run("review edits the untracked file", func(t *testing.T) {
		dir, before := leftover(t)
		write(t, dir, "notes.txt", "review edit\n")
		if !after(t, dir, before) {
			t.Fatal("editing a dirty untracked file must be dirty")
		}
	})
	t.Run("review deletes the untracked file", func(t *testing.T) {
		dir, before := leftover(t)
		if err := os.Remove(filepath.Join(dir, "notes.txt")); err != nil {
			t.Fatal(err)
		}
		if !after(t, dir, before) {
			t.Fatal("deleting a file must be dirty")
		}
	})
	t.Run("review stages the modified file", func(t *testing.T) {
		dir, before := leftover(t)
		run(t, dir, "add", "a.txt")
		if !after(t, dir, before) {
			t.Fatal("staging must be dirty")
		}
	})
	t.Run("review creates a new file", func(t *testing.T) {
		dir, before := leftover(t)
		write(t, dir, "new.txt", "n\n")
		if !after(t, dir, before) {
			t.Fatal("a new file must be dirty")
		}
	})
	t.Run("no baseline keeps the state", func(t *testing.T) {
		dir, _ := leftover(t)
		snap, err := Capture(dir)
		if err != nil {
			t.Fatal(err)
		}
		if !After(nil, snap).Dirty {
			t.Fatal("without a baseline the state decides")
		}
	})
}

// fakeGitFailingLsFiles is the test binary acting as git: the real git for
// everything except ls-files, which exits 128.
func fakeGitFailingLsFiles() int {
	for _, a := range os.Args[1:] {
		if a == "ls-files" {
			fmt.Fprintln(os.Stderr, "fatal: injected ls-files failure")
			return 128
		}
	}
	real, err := exec.LookPath("git")
	if err != nil {
		return 127
	}
	cmd := exec.Command(real, os.Args[1:]...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return ee.ExitCode()
		}
		return 127
	}
	return 0
}
