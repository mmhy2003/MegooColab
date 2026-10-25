package cmd

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
	"github.com/mmhy2003/megoocolab/runner/internal/conn"
	"github.com/mmhy2003/megoocolab/runner/internal/jobs"
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

// runConnection connects, prints state changes and executes the runs the
// server sends. It returns nil on cancellation and the friendly error when the
// server ends the session (revoked token, replaced by another runner); in both
// cases every run is stopped first.
func runConnection(ctx context.Context, out io.Writer, cfg config.Config, version string) error {
	cacheDir, err := os.UserCacheDir()
	if err != nil {
		return fmt.Errorf("cannot find the cache directory: %w", err)
	}
	cacheRoot := filepath.Join(cacheDir, "megoocolab")

	var c *conn.Client
	mgr := jobs.New(func(v any) error { return c.Send(v) }, cacheRoot)
	c = conn.New(cfg, version, mgr.Probe)
	c.OnState = func(s string) { fmt.Fprintln(out, s) }

	err = mgr.Serve(ctx, c)
	if errors.Is(err, context.Canceled) {
		return nil
	}
	return err
}
