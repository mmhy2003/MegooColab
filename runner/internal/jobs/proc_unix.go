//go:build !windows

package jobs

import (
	"os/exec"
	"syscall"
)

// ownProcessGroup puts the adapter in its own process group so the whole tree
// can be killed together.
func ownProcessGroup(cmd *exec.Cmd) { cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true} }

// killTree kills the adapter and everything it started.
func killTree(cmd *exec.Cmd) {
	if cmd == nil || cmd.Process == nil {
		return
	}
	_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	_ = cmd.Process.Kill()
}
