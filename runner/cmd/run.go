package cmd

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"

	"github.com/spf13/cobra"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
	"github.com/mmhy2003/megoocolab/runner/internal/conn"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

func newRunCmd(version string) *cobra.Command {
	return &cobra.Command{
		Use:   "run",
		Short: "Connect to MegooColab and wait for work",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := config.Load()
			if err != nil {
				return fmt.Errorf("cannot load config (%w); run: megoocolab-runner login --url URL --token TOKEN", err)
			}
			ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt)
			defer stop()
			return runConnection(ctx, cmd.OutOrStdout(), cfg, version)
		},
	}
}

// runConnection connects, prints state changes and logs received messages by
// type. It returns nil on cancellation and the friendly error when the server
// ends the session (revoked token, replaced by another runner).
func runConnection(ctx context.Context, out io.Writer, cfg config.Config, version string) error {
	c := conn.New(cfg, version, func() []protocol.AgentAvailability { return nil })
	c.OnState = func(s string) { fmt.Fprintln(out, s) }

	done := make(chan error, 1)
	go func() { done <- c.Run(ctx) }()
	for {
		select {
		case env, ok := <-c.Messages():
			if ok {
				fmt.Fprintf(out, "received %s\n", env.Type)
			}
		case err := <-done:
			if errors.Is(err, context.Canceled) {
				return nil
			}
			return err
		}
	}
}
