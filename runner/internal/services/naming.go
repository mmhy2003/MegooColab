package services

import (
	"crypto/sha256"
	"encoding/hex"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
)

const maxFolder = 24

var (
	notNameRe = regexp.MustCompile(`[^a-z0-9]+`)
	oursRe    = regexp.MustCompile(`^megoo-[a-z0-9]+(-[a-z0-9]+)*-[0-9a-f]{8}$`)
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

// ProjectName returns the Compose project of set in worktree:
// megoo-<folder>-<set>-<hash>. The folder makes it readable in docker ps, the
// hash of the whole path keeps two folders of the same name apart.
func ProjectName(worktree, set string) string {
	path := Canonical(worktree)
	folder := strings.Trim(notNameRe.ReplaceAllString(strings.ToLower(filepath.Base(path)), "-"), "-")
	if len(folder) > maxFolder {
		folder = strings.TrimRight(folder[:maxFolder], "-")
	}
	if folder == "" {
		folder = "wt"
	}
	sum := sha256.Sum256([]byte(path))
	return "megoo-" + folder + "-" + set + "-" + hex.EncodeToString(sum[:])[:8]
}

// IsOurs reports whether project has the shape ProjectName gives, so the
// runner never removes a Compose project it did not start.
func IsOurs(project string) bool {
	return oursRe.MatchString(project)
}
