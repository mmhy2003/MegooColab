// Package cmd holds the megoocolab-runner command line.
package cmd

import (
	"errors"
	"fmt"
	"os"
	"runtime"

	"github.com/kardianos/service"
	"github.com/spf13/cobra"

	"github.com/mmhy2003/megoocolab/runner/internal/conn"
)

// exitStoppedByServer is the exit status when the server ends the session for
// good (the token was revoked (4401) or another runner signed in (4409)) or
// when runner.json is missing or unusable. Restarting cannot help, so the
// systemd unit does not restart on it (RestartPreventExitStatus). 78 is EX_CONFIG: it needs the user's action.
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

// quietError is an error that is already in runner.log. In service mode stderr
// is that same file, so Execute does not print it again.
type quietError struct{ err error }

func (q quietError) Error() string { return q.err.Error() }
func (q quietError) Unwrap() error { return q.err }

// Execute runs the CLI and exits non-zero on error.
func Execute(version string) {
	if err := newRootCmd(version).Execute(); err != nil {
		code := exitCode(err, runtime.GOOS, service.Interactive())
		var q quietError
		if !errors.As(err, &q) {
			fmt.Fprintln(os.Stderr, "error:", err)
		}
		os.Exit(code)
	}
}

// exitCode is exitStoppedByServer when the server ended the session for good
// or the login is missing, else 1. On macOS in service mode it is 0 instead:
// the LaunchAgent restarts only after an unsuccessful exit, and nothing but
// `login` can help.
func exitCode(err error, goos string, interactive bool) int {
	code := 1
	if errors.Is(err, conn.ErrUnauthorized) || errors.Is(err, conn.ErrReplaced) || errors.Is(err, errNotLoggedIn) {
		code = exitStoppedByServer
	}
	if code == exitStoppedByServer && goos == "darwin" && !interactive {
		return 0
	}
	return code
}
