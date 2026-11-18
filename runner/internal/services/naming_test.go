package services

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestCanonicalResolvesSymlinks(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "target")
	if err := os.Mkdir(target, 0o755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(root, "link")
	if err := os.Symlink(target, link); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}
	if got, want := Canonical(link), Canonical(target); got != want {
		t.Errorf("Canonical(link) = %q, want %q", got, want)
	}
	if got := Canonical(filepath.Join(link, "..", "link", ".")); got != Canonical(target) {
		t.Errorf("Canonical(unclean) = %q, want %q", got, Canonical(target))
	}
	if !filepath.IsAbs(Canonical(".")) {
		t.Errorf("Canonical(.) is not absolute")
	}
}

func TestCanonicalKeepsMissingPaths(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "gone", "..", "Missing")
	want, _ := filepath.Abs(missing)
	if runtime.GOOS == "windows" {
		want = strings.ToLower(want)
	}
	if got := Canonical(missing); got != want {
		t.Errorf("Canonical(missing) = %q, want %q", got, want)
	}
}
