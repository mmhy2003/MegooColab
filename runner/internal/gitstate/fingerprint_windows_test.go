//go:build windows

package gitstate

import (
	"os"
	"strings"
	"testing"
)

// A name ending in a dot or a space is rewritten by the Win32 path rules to a
// different file; the fingerprint must read the file it was asked about.
func TestTrailingDotNameIsNotAliased(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(`\?\`+dir+`\a.`, []byte("dotted"), 0o644); err != nil {
		t.Skipf("cannot create the name: %v", err)
	}
	if err := os.WriteFile(dir+`\a`, []byte("plain"), 0o644); err != nil {
		t.Fatal(err)
	}
	fa, err := fingerprint(dir, []statusEntry{{raw: "?? a", path: "a"}})
	if err != nil {
		t.Fatal(err)
	}
	fd, err := fingerprint(dir, []statusEntry{{raw: "?? a", path: "a."}})
	if err != nil {
		t.Fatal(err)
	}
	if fa == fd || strings.Contains(fd, "deleted") {
		t.Fatalf("a. aliased to a: %q vs %q", fa, fd)
	}
}
