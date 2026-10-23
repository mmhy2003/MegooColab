package policy

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// InsideRoot reports whether path, once resolved, lies inside root, and returns
// the resolved absolute path to operate on.
//
// Resolution: an empty path is rejected; a relative path is joined to root; the
// result is cleaned; symlinks are evaluated on the deepest ancestor that exists
// (a write target may not exist yet), and the not-yet-existing tail is appended;
// the root is resolved the same way and the two are compared with filepath.Rel,
// rejecting anything that starts with "..". On Windows the comparison ignores
// case, and a path on a different volume is outside. Windows path forms that
// have no fixed meaning relative to the root ("\x", "C:x") are rejected.
func InsideRoot(root, path string) (string, bool) {
	if root == "" || path == "" || strings.ContainsRune(path, 0) {
		return "", false
	}
	if rootedWithoutVolume(path) || driveRelative(path) {
		return "", false
	}
	if !filepath.IsAbs(path) {
		path = filepath.Join(root, path)
	}
	realRoot, ok := resolve(root)
	if !ok {
		return "", false
	}
	real, ok := resolve(path)
	if !ok {
		return "", false
	}
	rel, err := filepath.Rel(fold(realRoot), fold(real))
	if err != nil {
		return "", false // different volumes
	}
	if rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) || filepath.IsAbs(rel) {
		return "", false
	}
	return real, true
}

// Relative returns the path of p relative to root, with forward slashes, if p
// is inside root. It is what run updates carry: never an absolute path.
func Relative(root, p string) (string, bool) {
	real, ok := InsideRoot(root, p)
	if !ok {
		return "", false
	}
	realRoot, ok := resolve(root)
	if !ok {
		return "", false
	}
	rel, err := filepath.Rel(fold(realRoot), fold(real))
	if err != nil {
		return "", false
	}
	if rel != "." {
		// take the tail from the unfolded path: folding can change byte lengths
		n := len(strings.Split(rel, string(filepath.Separator)))
		segs := strings.Split(real, string(filepath.Separator))
		rel = strings.Join(segs[len(segs)-n:], string(filepath.Separator))
	}
	return filepath.ToSlash(rel), true
}

func fold(s string) string {
	if runtime.GOOS == "windows" {
		return strings.ToLower(s)
	}
	return s
}

// rootedWithoutVolume: "\x" or "/x" on Windows depends on the current drive.
func rootedWithoutVolume(p string) bool {
	return runtime.GOOS == "windows" && filepath.VolumeName(p) == "" && (strings.HasPrefix(p, `\`) || strings.HasPrefix(p, "/"))
}

// driveRelative: "C:x" on Windows depends on the process's directory on C:.
func driveRelative(p string) bool {
	return runtime.GOOS == "windows" && filepath.VolumeName(p) != "" && !filepath.IsAbs(p)
}

// resolve makes p absolute and clean and evaluates symlinks on the deepest
// existing ancestor, keeping the missing tail. A symlink that exists but cannot
// be resolved (dangling) fails: creating its target would escape the check.
func resolve(p string) (string, bool) {
	abs, err := filepath.Abs(p)
	if err != nil {
		return "", false
	}
	abs = filepath.Clean(abs)
	var tail []string
	cur := abs
	for {
		real, err := filepath.EvalSymlinks(cur)
		if err == nil {
			for i := len(tail) - 1; i >= 0; i-- {
				real = filepath.Join(real, tail[i])
			}
			return real, true
		}
		if !errors.Is(err, os.ErrNotExist) {
			return "", false
		}
		if _, lerr := os.Lstat(cur); lerr == nil {
			return "", false // exists but unresolvable: dangling symlink
		}
		parent := filepath.Dir(cur)
		if parent == cur {
			return "", false
		}
		tail = append(tail, filepath.Base(cur))
		cur = parent
	}
}
