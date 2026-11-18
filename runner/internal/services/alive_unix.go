//go:build !windows

package services

import (
	"errors"
	"syscall"
)

// alive reports whether a process with this pid exists. EPERM means it does,
// but belongs to another user.
func alive(pid int) bool {
	if pid <= 0 {
		return false
	}
	err := syscall.Kill(pid, 0)
	return err == nil || errors.Is(err, syscall.EPERM)
}
