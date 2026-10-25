//go:build !windows

package gitstate

import (
	"os/exec"
	"syscall"
)

// killTreeOnCancel runs git in its own process group and kills the whole group
// when the call times out or is cancelled, so a child git starts (the checkout
// of `worktree add`, a filter) cannot keep writing after we gave up.
func killTreeOnCancel(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		return cmd.Process.Kill()
	}
}
