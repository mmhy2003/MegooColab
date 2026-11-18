package cmd

import (
	"errors"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/mmhy2003/megoocolab/runner/internal/services"
)

func newServicesCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "services",
		Short: "Start a worktree's test services for one command (megoocolab.toml)",
		Long:  "Start a worktree's test services for one command.\n\n" + services.Format,
	}
	cmd.AddCommand(newServicesRunCmd(), newServicesCleanCmd())
	return cmd
}

func newServicesRunCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "run <name> -- <command...>",
		Short: "Start the set, run the command with its variables, then remove the set",
		Args: func(cmd *cobra.Command, args []string) error {
			if cmd.ArgsLenAtDash() != 1 || len(args) < 2 {
				return errors.New("use: megoocolab-runner services run <name> -- <command...>")
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			dir, err := services.Dir()
			if err != nil {
				return err
			}
			cwd, err := os.Getwd()
			if err != nil {
				return err
			}
			ch := make(chan os.Signal, 2)
			signal.Notify(ch, os.Interrupt, syscall.SIGTERM)
			defer signal.Stop(ch)
			code := services.Run(cmd.Context(), services.Options{
				Dir:     dir,
				Cwd:     cwd,
				Set:     args[0],
				Command: args[1:],
				Stdin:   cmd.InOrStdin(),
				Stdout:  cmd.OutOrStdout(),
				Stderr:  cmd.ErrOrStderr(),
				Signals: ch,
			})
			if code != 0 {
				return exitError{code}
			}
			return nil
		},
	}
}

func newServicesCleanCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "clean",
		Short: "Remove the services of checks that have ended",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			dir, err := services.Dir()
			if err != nil {
				return err
			}
			before, err := services.List(dir)
			if err != nil {
				return err
			}
			sweepErr := services.Sweep(cmd.Context(), dir, time.Now())
			after, err := services.List(dir)
			if err != nil {
				return err
			}
			left := map[string]bool{}
			for _, rec := range after {
				left[rec.Project] = true
			}
			for _, rec := range before {
				if !left[rec.Project] {
					fmt.Fprintln(cmd.OutOrStdout(), "removed", rec.Project)
				}
			}
			if sweepErr != nil {
				fmt.Fprintln(cmd.ErrOrStderr(), "megoocolab-runner services:", sweepErr)
				return exitError{services.ExitServices}
			}
			return nil
		},
	}
}
