//go:build !windows

package gitstate

import (
	"fmt"
	"os"
	"syscall"
)

// fsPath is the path to hand to the os package; on Unix it is the path itself.
func fsPath(p string) string { return p }

// openNoFollow opens a file for reading without following a final link and
// without blocking on a FIFO.
func openNoFollow(p string) (*os.File, error) {
	return os.OpenFile(p, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
}

// sysStamp adds ctime, inode and device to a stamp. A file's ctime cannot be
// set back by an edit, unlike its mtime.
func sysStamp(fi os.FileInfo) string {
	st, ok := fi.Sys().(*syscall.Stat_t)
	if !ok {
		return ""
	}
	return fmt.Sprintf(":ctime:%d:ino:%d:dev:%d", ctimeNano(st), uint64(st.Ino), uint64(st.Dev))
}
