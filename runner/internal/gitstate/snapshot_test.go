package gitstate

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestMain(m *testing.M) {
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
