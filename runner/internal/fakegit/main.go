// Command fakegit is git, except that `ls-files` (which only gitstate.Capture
// runs) fails with status 128 once FAKEGIT_ALLOW_LS calls of it have been made;
// FAKEGIT_COUNTER is a file that counts them. Two calls make one capture. For
// tests of the callers of gitstate.Capture.
package main

import (
	"fmt"
	"os"
	"os/exec"
	"strconv"
)

func main() { os.Exit(run()) }

func run() int {
	for _, a := range os.Args[1:] {
		if a != "ls-files" {
			continue
		}
		allow, _ := strconv.Atoi(os.Getenv("FAKEGIT_ALLOW_LS"))
		counter := os.Getenv("FAKEGIT_COUNTER")
		n := 0
		if b, err := os.ReadFile(counter); err == nil {
			n, _ = strconv.Atoi(string(b))
		}
		n++
		_ = os.WriteFile(counter, []byte(strconv.Itoa(n)), 0o600)
		if n > allow {
			fmt.Fprintln(os.Stderr, "fatal: injected ls-files failure")
			return 128
		}
		break
	}
	real, err := exec.LookPath("git")
	if err != nil {
		return 127
	}
	cmd := exec.Command(real, os.Args[1:]...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			return ee.ExitCode()
		}
		return 127
	}
	return 0
}
