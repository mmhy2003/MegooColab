// Package cmd holds the megoocolab-runner command line.
package cmd

import (
	"errors"
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/mmhy2003/megoocolab/runner/internal/conn"
)

// exitStoppedByServer is the exit status when the server ends the session for
// good: the token was revoked (4401) or another runner signed in (4409).
// Restarting cannot help, so the systemd unit does not restart on it
// (RestartPreventExitStatus). 78 is EX_CONFIG: it needs the user's action.
const exitStoppedByServer = 78

func newRootCmd(version string) *cobra.Command {
	root := &cobra.Command{
		Use:           "megoocolab-runner",
		Short:         "Runs coding agents on this machine for MegooColab",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.AddCommand(newLoginCmd(), newDoctorCmd(), newVersionCmd(version), newRunCmd(version), newServiceCmd(), newSpikeCmd())
	return root
}

// Execute runs the CLI and exits non-zero on error.
func Execute(version string) {
	if err := newRootCmd(version).Execute(); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(exitCode(err))
	}
}

// exitCode is exitStoppedByServer when the server ended the session for good,
// else 1.
func exitCode(err error) int {
	if errors.Is(err, conn.ErrUnauthorized) || errors.Is(err, conn.ErrReplaced) {
		return exitStoppedByServer
	}
	return 1
}
