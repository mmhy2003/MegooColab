package services

import (
	"os"
	"path/filepath"
	"regexp"
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

func TestProjectNameStableAndPerPath(t *testing.T) {
	root := t.TempDir()
	a := filepath.Join(root, "a", "MC-52")
	b := filepath.Join(root, "b", "MC-52")
	for _, dir := range []string{a, b} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if ProjectName(a, "e2e") != ProjectName(a, "e2e") {
		t.Errorf("ProjectName is not stable")
	}
	if ProjectName(a, "e2e") == ProjectName(b, "e2e") {
		t.Errorf("two MC-52 folders under different parents share %q", ProjectName(a, "e2e"))
	}
	compose := regexp.MustCompile(`^[a-z0-9][a-z0-9_-]*$`)
	for _, name := range []string{ProjectName(a, "e2e"), ProjectName(b, "test")} {
		if !compose.MatchString(name) {
			t.Errorf("%q is not a valid Compose project name", name)
		}
		if !IsOurs(name) {
			t.Errorf("IsOurs(%q) = false", name)
		}
	}
	if got := ProjectName(a, "e2e"); !regexp.MustCompile(`^megoo-mc-52-e2e-[0-9a-f]{8}$`).MatchString(got) {
		t.Errorf("ProjectName(MC-52, e2e) = %q", got)
	}

	if got := ProjectName(filepath.Join(root, "My Repo!!"), "test"); !regexp.MustCompile(`^megoo-my-repo-test-[0-9a-f]{8}$`).MatchString(got) {
		t.Errorf("ProjectName(My Repo!!) = %q", got)
	}

	long := strings.Repeat("abcdefghij", 6)
	want := `^megoo-` + long[:24] + `-test-[0-9a-f]{8}$`
	if got := ProjectName(filepath.Join(root, long), "test"); !regexp.MustCompile(want).MatchString(got) {
		t.Errorf("ProjectName(60 chars) = %q, want it cut to 24", got)
	}
	// A cut that ends on a separator is trimmed again.
	cut := strings.Repeat("a", 23) + "--bbbb"
	if got := ProjectName(filepath.Join(root, cut), "test"); !regexp.MustCompile(`^megoo-a{23}-test-[0-9a-f]{8}$`).MatchString(got) {
		t.Errorf("ProjectName(cut on a dash) = %q", got)
	}
	if got := ProjectName(filepath.Join(root, "!!!"), "test"); !regexp.MustCompile(`^megoo-wt-test-[0-9a-f]{8}$`).MatchString(got) {
		t.Errorf("ProjectName(!!!) = %q, want the wt fallback", got)
	}
}

func TestIsOursNeverMatchesOtherProjects(t *testing.T) {
	for _, name := range []string{
		"megoocolab",
		"megoocolab-dev",
		"megoocolab-dev-db-1",
		"megoo-e2e",
		"megoo-x-e2e-1234567",
		"megoo--e2e-12345678",
		"MEGOO-X-E2E-12345678",
		"",
	} {
		if IsOurs(name) {
			t.Errorf("IsOurs(%q) = true", name)
		}
	}
	if !IsOurs("megoo-mc-52-e2e-3fa9c1d2") {
		t.Errorf("IsOurs(megoo-mc-52-e2e-3fa9c1d2) = false")
	}
}
