//go:build windows

package jobs

import (
	"os/exec"
	"strconv"
)

func ownProcessGroup(*exec.Cmd) {}

// killTree kills the adapter and its children (npx starts node, which starts
// the agent) with taskkill /T.
func killTree(cmd *exec.Cmd) {
	if cmd == nil || cmd.Process == nil {
		return
	}
	_ = exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(cmd.Process.Pid)).Run()
	_ = cmd.Process.Kill()
}
