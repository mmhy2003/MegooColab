package cmd

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/kardianos/service"
	"github.com/spf13/cobra"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
	"github.com/mmhy2003/megoocolab/runner/internal/conn"
	"github.com/mmhy2003/megoocolab/runner/internal/jobs"
)

func newRunCmd(version string) *cobra.Command {
	var background bool
	cmd := &cobra.Command{
		Use:   "run",
		Short: "Connect to MegooColab and wait for work",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if background {
				if relaunched, err := relaunchHiddenIfNeeded(); err != nil {
					return fmt.Errorf("cannot restart without a console window: %w", err)
				} else if relaunched {
					return nil
				}
			}
			cfg, err := config.Load()
			if err != nil {
				return fmt.Errorf("cannot load config (%w); run: megoocolab-runner login --url URL --token TOKEN", err)
			}
			ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			out := cmd.OutOrStdout()
			// Under a service manager (or with --background) there is no
			// terminal, so state lines go to <cache>/megoocolab/logs/runner.log.
			if background || !service.Interactive() {
				root, err := cacheRoot()
				if err != nil {
					return err
				}
				f, err := openRunLog(root)
				if err != nil {
					return fmt.Errorf("cannot open the log file: %w", err)
				}
				defer f.Close()
				out = f
				// `service stop` on Windows asks for a graceful stop by creating
				// a stop file; turn it into cancellation so agents are cancelled.
				cleanup, err := beginBackground(root)
				if err != nil {
					return fmt.Errorf("cannot write the pid file: %w", err)
				}
				defer cleanup()
				var cancel context.CancelFunc
				ctx, cancel = context.WithCancel(ctx)
				defer cancel()
				go watchStopFile(ctx, stopPath(root), time.Second, cancel)
			}
			return runConnection(ctx, out, cfg, version)
		},
	}
	cmd.Flags().BoolVar(&background, "background", false, "write output to the log file instead of stdout (used by the service)")
	_ = cmd.Flags().MarkHidden("background")
	return cmd
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
