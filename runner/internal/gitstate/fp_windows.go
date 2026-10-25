//go:build windows

package gitstate

import (
	"os"
	"path/filepath"
	"strings"
)

// fsPath turns p into an extended-length path (\\?\C:\... or \\?\UNC\server\share\...)
// so that Win32 does not normalise it: without the prefix a name ending in a dot
// or a space names a different file, and names such as NUL or COM1 name devices.
// filepath.Abs is not used because it goes through GetFullPathName, which does
// that very normalisation.
func fsPath(p string) string {
	if !filepath.IsAbs(p) {
		wd, err := os.Getwd()
		if err != nil {
			return p
		}
		p = filepath.Join(wd, p)
	}
	p = filepath.Clean(p)
	switch {
	case strings.HasPrefix(p, `\\?\`):
		return p
	case strings.HasPrefix(p, `\\`):
		return `\\?\UNC\` + p[2:]
	}
	return `\\?\` + p
}

func openNoFollow(p string) (*os.File, error) { return os.Open(p) }

// sysStamp is empty on Windows: Go's FileInfo carries no change time or file
// id there, so an object that is not hashed is told apart by size and mtime
// alone, and an edit that keeps both can go unseen.
func sysStamp(os.FileInfo) string { return "" }
