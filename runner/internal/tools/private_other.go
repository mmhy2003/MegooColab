//go:build !windows

package tools

import "os"

// MakePrivate lets only the current user read or write path.
func MakePrivate(path string) error { return os.Chmod(path, 0o600) }
