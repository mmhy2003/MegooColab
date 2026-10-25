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
		os.WriteFile(filepath.Join(dir, n), []byte("0123456789"), 0o644)
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
	before, _ := Capture(dir)
	// a stash probe that fails after Read works: make the fingerprint fail via an unreadable-free path is hard,
	// so fail only the later calls by pointing at a repo where refs/stash lookup errors.
	if err := os.WriteFile(filepath.Join(dir, ".git", "refs", "stash"), []byte("garbage\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	st, err := CaptureAfter(dir, &before)
	if err == nil {
		t.Skip("git tolerated the bad stash ref")
	}
	if !st.Dirty || st.Head == nil || st.Branch == nil {
		t.Fatalf("%+v", st)
	}
}
