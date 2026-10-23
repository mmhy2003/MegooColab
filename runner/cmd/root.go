// Package cmd holds the megoocolab-runner command line.
package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func newRootCmd(version string) *cobra.Command {
	root := &cobra.Command{
		Use:           "megoocolab-runner",
		Short:         "Runs coding agents on this machine for MegooColab",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.AddCommand(newLoginCmd(), newDoctorCmd(), newVersionCmd(version))
	return root
}

// Execute runs the CLI and exits non-zero on error.
func Execute(version string) {
	if err := newRootCmd(version).Execute(); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
