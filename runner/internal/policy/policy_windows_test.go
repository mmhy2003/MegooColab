//go:build windows

package policy_test

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/policy"
)

func TestWindowsCaseFold(t *testing.T) {
	root := t.TempDir()
	if _, ok := policy.InsideRoot(root, strings.ToUpper(filepath.Join(root, "A.txt"))); !ok {
		t.Fatal("upper-cased path inside root must be inside")
	}
	if _, ok := policy.InsideRoot(strings.ToLower(root), filepath.Join(root, "A.txt")); !ok {
		t.Fatal("lower-cased root must match")
	}
	if _, ok := policy.InsideRoot(root, strings.ToUpper(filepath.Join(root, "..", "x"))); ok {
		t.Fatal("outside stays outside")
	}
}

func TestWindowsForms(t *testing.T) {
	root := t.TempDir()
	vol := filepath.VolumeName(root)
	other := "Z:"
	if strings.EqualFold(vol, other) {
		other = "Y:"
	}
	for _, p := range []string{
		`C:\..\x`, other + `\x`, other + `x`, vol + `x`, // C:x is drive-relative: resolved against the process cwd, never the root
		`\Windows\x`, `/Windows/x`, `\\server\share\x`, `\\?\` + other + `\x`,
		`..\x`, `..\..\Windows\win.ini`, root + `\..\x`, strings.ReplaceAll(root, `\`, `/`) + `/../x`,
	} {
		if _, ok := policy.InsideRoot(root, p); ok {
			t.Errorf("%q must be outside", p)
		}
	}
	if _, ok := policy.InsideRoot(root, strings.ReplaceAll(root, `\`, `/`)+`/ok/x.txt`); !ok {
		t.Error("forward-slash path inside root must be inside")
	}
	if _, ok := policy.InsideRoot(root, `sub\x.txt`); !ok {
		t.Error("backslash relative must be inside")
	}
	if !policy.ReadOnlyCommand("C:/Git/cmd/git.exe status") || !policy.ReadOnlyCommand(`DIR /b`) {
		t.Error("windows commands")
	}
}
