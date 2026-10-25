package gitstate

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

func run(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t"}, args...)...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

func repo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	run(t, dir, "init", "-q")
	if err := os.WriteFile(filepath.Join(dir, "a.txt"), []byte("a\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, dir, "add", ".")
	run(t, dir, "commit", "-q", "-m", "init")
	return dir
}

func TestReadDetectsCommitAndDirtyIgnoringMegoo(t *testing.T) {
	dir := repo(t)
	st, err := Read(dir)
	if err != nil || st.Head == nil || st.Branch == nil || st.Dirty {
		t.Fatalf("clean = %+v, %v", st, err)
	}
	if *st.Head != run(t, dir, "rev-parse", "HEAD") {
		t.Fatalf("head = %q", *st.Head)
	}

	// .megoocolab/ files do not make the tree dirty, even without the exclude.
	if err := os.MkdirAll(filepath.Join(dir, ".megoocolab"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, ".megoocolab", "plan.md"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if st, _ = Read(dir); st.Dirty {
		t.Fatal(".megoocolab must be ignored")
	}

	if err := os.WriteFile(filepath.Join(dir, "new file.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if st, _ = Read(dir); !st.Dirty {
		t.Fatal("untracked file must make it dirty")
	}
	run(t, dir, "add", ".")
	run(t, dir, "commit", "-q", "-m", "two")
	st2, _ := Read(dir)
	if st2.Dirty || *st2.Head == *st.Head {
		t.Fatalf("after commit = %+v", st2)
	}
}

func TestReadEmptyRepoAndNotARepo(t *testing.T) {
	dir := t.TempDir()
	run(t, dir, "init", "-q")
	st, err := Read(dir)
	if err != nil || st.Head != nil || st.Dirty {
		t.Fatalf("empty repo = %+v, %v", st, err)
	}
	if _, err := Read(t.TempDir()); err == nil {
		t.Fatal("not a repo must error")
	}
}

func TestReadTruncatesBranch(t *testing.T) {
	dir := repo(t)
	long := strings.Repeat("e", 100)
	run(t, dir, "checkout", "-q", "-b", long)
	st, err := Read(dir)
	if err != nil || len(*st.Branch) != 100 {
		t.Fatalf("branch = %+v, %v", st, err)
	}
	if got := truncateRunes(strings.Repeat("\u00e9", 250), 200); len([]rune(got)) != 200 || !strings.HasSuffix(got, "\u00e9") {
		t.Fatal("truncation must cut on rune boundaries")
	}
}

func TestMaterializeRejectsEscapes(t *testing.T) {
	dir := repo(t)
	for _, p := range []string{
		"../x", "/abs", `C:\x`, ".megoocolab/../x", ".megoocolab/", ".megoocolab", "x/y",
		".megoocolab/a/../b", ".megoocolab//a", ".megoocolab/a\\b", ".megoocolab/C:x",
		".megoocolab/CON", ".megoocolab/nul.txt", ".megoocolab/a.", ".megoocolab/a b", ".megoocolab/./a",
	} {
		if err := Materialize(dir, []protocol.File{{Path: p, Content: "x"}}); err == nil {
			t.Errorf("%q accepted", p)
		}
	}
	big := protocol.File{Path: ".megoocolab/big", Content: strings.Repeat("x", MaxFilesBytes+1)}
	if err := Materialize(dir, []protocol.File{big}); err == nil {
		t.Error("oversize accepted")
	}
	if _, err := os.Stat(filepath.Join(dir, ".megoocolab")); err == nil {
		t.Error("a rejected set must write nothing")
	}
}

func TestMaterializeWritesReadOnlyAndExcludes(t *testing.T) {
	dir := repo(t)
	files := []protocol.File{{Path: ".megoocolab/plan.md", Content: "v1"}, {Path: ".megoocolab/sub/notes.md", Content: "n"}}
	if err := Materialize(dir, files); err != nil {
		t.Fatal(err)
	}
	p := filepath.Join(dir, ".megoocolab", "plan.md")
	fi, err := os.Stat(p)
	if err != nil || fi.Mode().Perm()&0o200 != 0 {
		t.Fatalf("not read-only: %v %v", fi, err)
	}

	// replace a read-only copy, drop files not in the new set
	if err := Materialize(dir, []protocol.File{{Path: ".megoocolab/plan.md", Content: "v2"}}); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(p); string(b) != "v2" {
		t.Fatalf("content = %q", b)
	}
	if _, err := os.Stat(filepath.Join(dir, ".megoocolab", "sub")); err == nil {
		t.Fatal("stale file/dir not removed")
	}

	if err := Materialize(dir, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(p); err == nil {
		t.Fatal("empty set must clear the files")
	}

	b, _ := os.ReadFile(filepath.Join(dir, ".git", "info", "exclude"))
	if strings.Count(string(b), "/.megoocolab/") != 1 {
		t.Fatalf("exclude = %q", b)
	}
	if st, _ := Read(dir); st.Dirty {
		t.Fatal("excluded files must not dirty the tree")
	}
}

func TestMaterializeInLinkedWorktreeUsesCommonDir(t *testing.T) {
	dir := repo(t)
	wt := filepath.Join(t.TempDir(), "wt")
	run(t, dir, "worktree", "add", "-q", "-b", "feature", wt)
	if err := Materialize(wt, []protocol.File{{Path: ".megoocolab/a.md", Content: "x"}}); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(filepath.Join(dir, ".git", "info", "exclude"))
	if !strings.Contains(string(b), "/.megoocolab/") {
		t.Fatalf("exclude = %q", b)
	}
	if out := run(t, wt, "status", "--porcelain"); out != "" {
		t.Fatalf("status = %q", out)
	}
}

func TestCommitRepoFilesOnlyUnderDocsSuperpowers(t *testing.T) {
	dir := repo(t)
	before := run(t, dir, "rev-parse", "HEAD")
	for _, p := range []string{"a.txt", "docs/other.md", "docs/superpowers/", "docs/superpowers/../x.md", "/docs/superpowers/x.md", "docs/superpowers/a b.md"} {
		if err := CommitRepoFiles(dir, []protocol.File{{Path: p, Content: "x"}}, "m"); err == nil {
			t.Errorf("%q accepted", p)
		}
	}
	if run(t, dir, "rev-parse", "HEAD") != before || run(t, dir, "status", "--porcelain") != "" {
		t.Fatal("rejected paths changed the repo")
	}

	files := []protocol.File{{Path: "docs/superpowers/specs/design.md", Content: "# d\n"}}
	if err := CommitRepoFiles(dir, files, "docs: design"); err != nil {
		t.Fatal(err)
	}
	after := run(t, dir, "rev-parse", "HEAD")
	if after == before || run(t, dir, "log", "-1", "--format=%s") != "docs: design" {
		t.Fatal("not committed")
	}
	if run(t, dir, "status", "--porcelain") != "" {
		t.Fatal("tree dirty after commit")
	}
	// unchanged: no new commit
	if err := CommitRepoFiles(dir, files, "again"); err != nil {
		t.Fatal(err)
	}
	if run(t, dir, "rev-parse", "HEAD") != after {
		t.Fatal("no-op created a commit")
	}
}

func TestCommitRepoFilesSkipsHooksAndFallsBackToIdentity(t *testing.T) {
	dir := repo(t)
	hook := filepath.Join(dir, ".git", "hooks", "pre-commit")
	if err := os.WriteFile(hook, []byte("#!/bin/sh\nexit 1\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	// no identity configured anywhere visible to this repo
	t.Setenv("GIT_CONFIG_GLOBAL", filepath.Join(t.TempDir(), "none"))
	t.Setenv("GIT_CONFIG_SYSTEM", filepath.Join(t.TempDir(), "none"))
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	if err := CommitRepoFiles(dir, []protocol.File{{Path: "docs/superpowers/p.md", Content: "p"}}, "docs"); err != nil {
		t.Fatal(err)
	}
	if got := run(t, dir, "log", "-1", "--format=%an <%ae>"); got != "MegooColab <megoocolab@localhost>" {
		t.Fatalf("author = %q", got)
	}
}
