//go:build linux

package gitstate

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestUnreadableWalkEntriesAreStamped(t *testing.T) {
	dir := repo(t)
	run(t, dir, "init", "-q", "sub")
	locked := filepath.Join(dir, "sub", "locked")
	if err := os.Mkdir(locked, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(locked, "x"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(locked, 0o000); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chmod(locked, 0o755) })
	if _, err := os.ReadDir(locked); err == nil {
		t.Skip("running as a user that can read mode 000 directories")
	}
	fp, err := fingerprint(dir, []statusEntry{{raw: "?? sub/", path: "sub/"}})
	if err != nil || !strings.Contains(fp, "locked=unreadable:permission:size:") {
		t.Fatalf("%q %v", fp, err)
	}
}
