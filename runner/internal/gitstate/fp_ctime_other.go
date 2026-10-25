//go:build !windows && !linux && !darwin && !freebsd

package gitstate

import "syscall"

// No ctime on these platforms here: the stamp keeps size, mtime, inode and device.
func ctimeNano(*syscall.Stat_t) int64 { return 0 }
