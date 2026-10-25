package gitstate

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func awkwardNames() map[string]string {
	m := map[string]string{"quote": `"x`}
	m["newline"] = "a\nb"
	return m
}

func TestAwkwardFileNamesAreSeenByTheFingerprint(t *testing.T) {
	for label, name := range awkwardNames() {
		mk := func(t *testing.T, dir, content string) bool {
			if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o644); err != nil {
				if runtime.GOOS == "windows" { // Windows forbids both names
					t.Skipf("filesystem rejects the name: %v", err)
				}
				t.Fatal(err)
			}
			return true
		}
		t.Run(label+" created during the run", func(t *testing.T) {
			dir := repo(t)
			before, err := Capture(dir)
			if err != nil {
				t.Fatal(err)
			}
			mk(t, dir, "one")
			st, err := CaptureAfter(dir, &before)
			if err != nil || !st.Dirty {
				t.Fatalf("dirty=%v err=%v", st.Dirty, err)
			}
		})
		t.Run(label+" left by an earlier run", func(t *testing.T) {
			dir := repo(t)
			mk(t, dir, "one")
			before, err := Capture(dir)
			if err != nil {
				t.Fatalf("capture: %v", err)
			}
			st, err := CaptureAfter(dir, &before)
			if err != nil || st.Dirty {
				t.Fatalf("dirty=%v err=%v", st.Dirty, err)
			}
			mk(t, dir, "two")
			st, err = CaptureAfter(dir, &before)
			if err != nil || !st.Dirty {
				t.Fatalf("edit: dirty=%v err=%v", st.Dirty, err)
			}
		})
	}
}

func TestOverBudgetFileIsMarkedBySizeAndMtime(t *testing.T) {
	old := maxFileBytes
	maxFileBytes = 10
	t.Cleanup(func() { maxFileBytes = old })
	dir := repo(t)
	p := filepath.Join(dir, "big.bin")
	if err := os.WriteFile(p, []byte("0123456789ABC"), 0o644); err != nil {
		t.Fatal(err)
	}
	entries := statusEntries(mustStatus(t, dir))
	fp, err := fingerprint(dir, entries)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(fp, "size:13:mtime:") {
		t.Fatalf("fingerprint = %q", fp)
	}
	// same size, new mtime: still noticed
	later := time.Now().Add(time.Hour)
	if err := os.Chtimes(p, later, later); err != nil {
		t.Fatal(err)
	}
	fp2, _ := fingerprint(dir, entries)
	if fp2 == fp {
		t.Fatal("mtime change not noticed")
	}
	// small file is content-hashed
	maxFileBytes = 100
	fp3, _ := fingerprint(dir, entries)
	if strings.Contains(fp3, "size:") {
		t.Fatalf("under budget must be hashed: %q", fp3)
	}
}

func TestTotalBudgetFallsBackToSizeMtime(t *testing.T) {
	oldF, oldT := maxFileBytes, maxTotalBytes
	maxFileBytes, maxTotalBytes = 100, 15
	t.Cleanup(func() { maxFileBytes, maxTotalBytes = oldF, oldT })
	dir := repo(t)
	for _, n := range []string{"f1", "f2"} {
		if err := os.WriteFile(filepath.Join(dir, n), []byte("0123456789"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	fp, err := fingerprint(dir, statusEntries(mustStatus(t, dir)))
	if err != nil || strings.Count(fp, "size:10:mtime:") != 1 {
		t.Fatalf("%q %v", fp, err)
	}
}

func mustStatus(t *testing.T, dir string) string {
	t.Helper()
	_, status, err := read(dir)
	if err != nil {
		t.Fatal(err)
	}
	return status
}

func TestCaptureAfterFailsClosedWhenGitFails(t *testing.T) {
	dir := repo(t)
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("GITSTATE_FAKE_GIT", "1")
	restore := OverrideForTest(os.Args[0], 300*time.Millisecond)
	defer restore()
	st, err := CaptureAfter(dir, &before)
	if err == nil {
		t.Fatal("the cause must be returned for the log")
	}
	if !st.Dirty {
		t.Fatalf("must be dirty: %+v", st)
	}
	if st.Head != nil || st.Branch != nil {
		t.Fatalf("nothing readable, fields must be null: %+v", st)
	}
	// no baseline: nothing to compare, nothing to claim
	if st, err := CaptureAfter(dir, nil); err == nil || st.Dirty {
		t.Fatalf("no baseline: %+v %v", st, err)
	}
}

func TestCaptureAfterKeepsReadableHeadAndBranch(t *testing.T) {
	dir := repo(t)
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	// git works except ls-files: Read succeeds, Capture does not
	t.Setenv("GITSTATE_FAKE_GIT", "fail-ls-files")
	restore := OverrideForTest(os.Args[0], 20*time.Second)
	defer restore()
	st, err := CaptureAfter(dir, &before)
	if err == nil {
		t.Fatal("the injected failure must surface")
	}
	if !st.Dirty || st.Head == nil || st.Branch == nil || *st.Head != *before.State.Head {
		t.Fatalf("%+v", st)
	}
}

func TestSmallestFilesAreHashedFirst(t *testing.T) {
	oldF, oldT := maxFileBytes, maxTotalBytes
	maxFileBytes, maxTotalBytes = 1000, 100
	t.Cleanup(func() { maxFileBytes, maxTotalBytes = oldF, oldT })
	dir := repo(t)
	junk, small := filepath.Join(dir, "aaa-junk"), filepath.Join(dir, "zzz-small")
	if err := os.WriteFile(junk, []byte(strings.Repeat("j", 90)), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(small, []byte("0123456789abcdefghij"), 0o644); err != nil {
		t.Fatal(err)
	}
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	fi, _ := os.Stat(small)
	if err := os.WriteFile(small, []byte("ABCDEFGHIJabcdefghij"), 0o644); err != nil { // same size
		t.Fatal(err)
	}
	if err := os.Chtimes(small, fi.ModTime(), fi.ModTime()); err != nil { // same mtime
		t.Fatal(err)
	}
	st, err := CaptureAfter(dir, &before)
	if err != nil || !st.Dirty {
		t.Fatalf("an edit of a small file hid behind a big one: dirty=%v err=%v", st.Dirty, err)
	}
}

func TestEditsInsideANestedRepoAreSeen(t *testing.T) {
	dir := repo(t)
	sub := filepath.Join(dir, "sub")
	run(t, dir, "init", "-q", "sub")
	if err := os.WriteFile(filepath.Join(sub, "f.txt"), []byte("one"), 0o644); err != nil {
		t.Fatal(err)
	}
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	st, err := CaptureAfter(dir, &before)
	if err != nil || st.Dirty {
		t.Fatalf("untouched: dirty=%v err=%v", st.Dirty, err)
	}
	if err := os.WriteFile(filepath.Join(sub, "f.txt"), []byte("two"), 0o644); err != nil {
		t.Fatal(err)
	}
	st, err = CaptureAfter(dir, &before)
	if err != nil || !st.Dirty {
		t.Fatalf("edit inside sub/: dirty=%v err=%v", st.Dirty, err)
	}
}

func TestFingerprintDeadlineFailsClosed(t *testing.T) {
	dir := repo(t)
	if err := os.WriteFile(filepath.Join(dir, "n.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	old := fingerprintTimeout
	fingerprintTimeout = -time.Second
	defer func() { fingerprintTimeout = old }()
	st, err := CaptureAfter(dir, &before)
	if err == nil || !st.Dirty {
		t.Fatalf("an expired deadline must fail closed: %+v %v", st, err)
	}
}

func TestPinnedGitDirCannotBeRedirected(t *testing.T) {
	main := repo(t)
	wt := filepath.Join(t.TempDir(), "wt")
	run(t, main, "worktree", "add", "-q", "-b", "wtb", wt)
	good, err := Capture(wt)
	if err != nil {
		t.Fatal(err)
	}
	// a crafted repository with a different HEAD
	evil := repo(t)
	if err := os.WriteFile(filepath.Join(evil, "b.txt"), []byte("b"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, evil, "add", ".")
	run(t, evil, "commit", "-q", "-m", "evil")
	if err := os.WriteFile(filepath.Join(wt, ".git"), []byte("gitdir: "+filepath.ToSlash(filepath.Join(evil, ".git"))+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	snap, err := Capture(wt)
	if err != nil {
		t.Fatal(err)
	}
	if *snap.State.Head != *good.State.Head || *snap.State.Branch != "wtb" {
		t.Fatalf("capture followed the rewritten .git: %+v", snap.State)
	}
}

func TestHardenedArgsPinStatCaching(t *testing.T) {
	a := strings.Join(HardenedArgs(), " ")
	for _, want := range []string{"core.checkStat=default", "core.trustctime=true"} {
		if !strings.Contains(a, want) {
			t.Fatalf("missing %s in %s", want, a)
		}
	}
}
