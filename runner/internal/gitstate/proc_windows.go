//go:build windows

package gitstate

import (
	"os/exec"
	"strconv"
)

// killTreeOnCancel kills git and everything it started (taskkill /T) when the
// call times out or is cancelled, so a child git starts (the checkout of
// `worktree add`, a filter) cannot keep writing, or keep the worktree's
// directory in use, after we gave up. It mirrors jobs.killTree, which this
// package cannot import.
func killTreeOnCancel(cmd *exec.Cmd) {
	cmd.Cancel = func() error {
		_ = exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(cmd.Process.Pid)).Run()
		return cmd.Process.Kill()
	}
}
