package gitstate

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

func exists(p string) bool { _, err := os.Lstat(p); return err == nil }

func slash(p string) string { return filepath.ToSlash(p) }

func writeHook(t *testing.T, dir, name, marker string) {
	t.Helper()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	body := "#!/bin/sh\necho ran >> \"" + slash(marker) + "\"\nexit 1\n"
	if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o755); err != nil {
		t.Fatal(err)
	}
}

func TestNoRepoHookRunsDuringCommitRepoFiles(t *testing.T) {
	dir := repo(t)
	markers := t.TempDir()
	hooks := filepath.Join(dir, ".git", "hooks")
	custom := filepath.Join(t.TempDir(), "custom-hooks")
	run(t, dir, "config", "core.hooksPath", custom) // an agent-written config redirecting hooks
	for _, h := range []string{"pre-commit", "prepare-commit-msg", "commit-msg", "post-commit", "post-index-change"} {
		writeHook(t, hooks, h, filepath.Join(markers, h))
		writeHook(t, custom, h, filepath.Join(markers, "custom-"+h))
	}
	if err := CommitRepoFiles(dir, []protocol.File{{Path: "docs/superpowers/p.md", Content: "p"}}, "docs"); err != nil {
		t.Fatal(err)
	}
	if _, err := Read(dir); err != nil {
		t.Fatal(err)
	}
	ran, _ := os.ReadDir(markers)
	for _, m := range ran {
		t.Errorf("hook ran: %s", m.Name())
	}
}

func TestFsmonitorNeverRuns(t *testing.T) {
	dir := repo(t)
	marker := filepath.Join(t.TempDir(), "fsmonitor-ran")
	run(t, dir, "config", "core.fsmonitor", "echo ran >> \""+slash(marker)+"\"")
	if _, err := Read(dir); err != nil {
		t.Fatal(err)
	}
	if exists(marker) {
		t.Fatal("core.fsmonitor command ran")
	}
}

func TestDirtyIgnoresOnlyTheMegooDirectory(t *testing.T) {
	if !dirty("?? .megoocolab\x00") {
		t.Error("a file named .megoocolab is a change")
	}
	if dirty("?? .megoocolab/plan.md\x00") {
		t.Error(".megoocolab/ content must be ignored")
	}
}

func TestMaterializeRefusesSymlinkedExclude(t *testing.T) {
	dir := repo(t)
	victim := filepath.Join(t.TempDir(), "victim")
	if err := os.WriteFile(victim, []byte("keep\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	ex := filepath.Join(dir, ".git", "info", "exclude")
	_ = os.Remove(ex)
	if err := os.Symlink(victim, ex); err != nil {
		t.Skip("symlinks unavailable:", err)
	}
	if err := Materialize(dir, []protocol.File{{Path: ".megoocolab/a.md", Content: "x"}}); err == nil {
		t.Fatal("symlinked info/exclude accepted")
	}
	if b, _ := os.ReadFile(victim); string(b) != "keep\n" {
		t.Fatalf("victim modified: %q", b)
	}
}

func TestMaterializeRefusesRedirectedGitDir(t *testing.T) {
	dir := repo(t)
	other := repo(t)
	wt := filepath.Join(t.TempDir(), "wt")
	run(t, dir, "worktree", "add", "-q", "-b", "feature", wt)
	// the worktree's .git file now points at some other repository
	if err := os.WriteFile(filepath.Join(wt, ".git"), []byte("gitdir: "+slash(filepath.Join(other, ".git"))+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := Materialize(wt, []protocol.File{{Path: ".megoocolab/a.md", Content: "x"}}); err == nil {
		t.Fatal("redirected git dir accepted")
	}
	if b, _ := os.ReadFile(filepath.Join(other, ".git", "info", "exclude")); strings.Contains(string(b), ".megoocolab") {
		t.Fatal("wrote into the other repository")
	}
}

func TestMaterializeReplacesNonDirectoryMegoocolab(t *testing.T) {
	dir := repo(t)
	if err := os.WriteFile(filepath.Join(dir, ".megoocolab"), []byte("junk"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := Materialize(dir, []protocol.File{{Path: ".megoocolab/a.md", Content: "x"}}); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(filepath.Join(dir, ".megoocolab", "a.md")); string(b) != "x" {
		t.Fatal("file not written")
	}
}

func TestMaterializeNeverFollowsMegoocolabLink(t *testing.T) {
	dir := repo(t)
	target := t.TempDir()
	keep := filepath.Join(target, "keep.txt")
	if err := os.WriteFile(keep, []byte("keep"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(dir, ".megoocolab")); err != nil {
		t.Skip("symlinks unavailable:", err)
	}
	if err := Materialize(dir, []protocol.File{{Path: ".megoocolab/a.md", Content: "x"}}); err != nil {
		t.Fatal(err)
	}
	if !exists(keep) || exists(filepath.Join(target, "a.md")) {
		t.Fatal("followed the link")
	}
	if fi, err := os.Lstat(filepath.Join(dir, ".megoocolab")); err != nil || !fi.IsDir() {
		t.Fatalf(".megoocolab is not a real directory: %v", err)
	}
}

func TestCommitRepoFilesForcesIgnoredPaths(t *testing.T) {
	dir := repo(t)
	if err := os.WriteFile(filepath.Join(dir, ".gitignore"), []byte("docs/\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, dir, "add", ".gitignore")
	run(t, dir, "commit", "-q", "-m", "ignore docs")
	if err := CommitRepoFiles(dir, []protocol.File{{Path: "docs/superpowers/p.md", Content: "p"}}, "docs"); err != nil {
		t.Fatal(err)
	}
	if run(t, dir, "ls-files", "docs/superpowers/p.md") == "" {
		t.Fatal("not committed")
	}
}
