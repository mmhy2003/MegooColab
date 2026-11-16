//go:build !windows

package cmd

import (
	"errors"
	"os"
)

// Only Windows runs a launcher and a supervisor (see backgroundRole); these
// stubs keep run.go platform independent.

func spawnSupervisor(exe string) error { return errors.New("only used on Windows") }

func runWorkerProcess(exe string, logf *os.File) func() (int, error) {
	return func() (int, error) { return 0, errors.New("only used on Windows") }
}

func otherRunnerPID(root, exe string) (int, bool) { return 0, false }
