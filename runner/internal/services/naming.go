package services

import (
	"path/filepath"
	"runtime"
	"strings"
)

// Canonical returns one spelling of path, so the same folder always gives the
// same worktree identity: absolute, symlinks resolved (when the path exists),
// cleaned, and lower-cased on Windows, whose file names ignore case.
func Canonical(path string) string {
	abs, err := filepath.Abs(path)
	if err != nil {
		abs = path
	}
	if real, err := filepath.EvalSymlinks(abs); err == nil {
		abs = real
	}
	abs = filepath.Clean(abs)
	if runtime.GOOS == "windows" {
		abs = strings.ToLower(abs)
	}
	return abs
}
