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
			if !background && service.Interactive() {
				cfg, err := loadLogin()
				if err != nil {
					return err
				}
				ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
				defer stop()
				return runConnection(ctx, cmd.OutOrStdout(), cfg, version)
			}
			return runService(cmd.Context(), roleSingle, version)
		},
	}
	cmd.Flags().BoolVar(&background, "background", false, "write output to the log file instead of stdout (used by the service)")
	_ = cmd.Flags().MarkHidden("background")
	return cmd
}

// runService runs under a service manager (or with --background), where there
// is no terminal: everything goes to <cache>/megoocolab/logs/runner.log.
func runService(ctx context.Context, role bgRole, version string) error {
	root, rootErr := cacheRoot()
	return runServiceAt(ctx, role, version, root, rootErr, os.TempDir())
}

// runServiceAt opens the log before anything else can fail, so that every
// start and every startup error leaves a timestamped line behind.
func runServiceAt(ctx context.Context, role bgRole, version, root string, rootErr error, tempDir string) error {
	var logf *os.File
	if role == roleWorker {
		logf = os.Stderr // the supervisor pointed stdout and stderr at runner.log
	} else {
		logRoot := root
		if rootErr != nil {
			logRoot = ""
		}
		logf, _ = openServiceLog(logRoot, tempDir)
		if logf != nil {
			defer logf.Close()
		}
	}
	var log io.Writer = io.Discard
	if logf != nil {
		log = newTSWriter(logf, time.Now)
	}
	fmt.Fprintf(log, "starting megoocolab-runner %s (pid %d)\n", version, os.Getpid())
	err := serveRole(ctx, role, version, root, rootErr, log)
	if err != nil {
		fmt.Fprintf(log, "error: %v\n", err)
		if role == roleWorker {
			return quietError{err}
		}
	}
	return err
}

// serveRole does the work of one service-mode process.
func serveRole(ctx context.Context, role bgRole, version, root string, rootErr error, log io.Writer) error {
	if rootErr != nil {
		return rootErr
	}
	switch role {
	case roleSingle, roleWorker:
		cfg, err := loadLogin()
		if err != nil {
			return err
		}
		ctx, stop := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
		defer stop()
		if role == roleSingle {
			cleanup, err := beginBackground(root)
			if err != nil {
				return fmt.Errorf("cannot write the pid file: %w", err)
			}
			defer cleanup()
		}
		// `service stop` on Windows asks for a graceful stop by creating
		// a stop file; turn it into cancellation so agents are cancelled.
		ctx, cancel := context.WithCancel(ctx)
		defer cancel()
		go watchStopFile(ctx, stopPath(root), time.Second, cancel)
		return runConnection(ctx, log, cfg, version)
	default:
		return fmt.Errorf("unknown background role %d", role)
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
	mgr.ServerURL, mgr.Token = cfg.URL, cfg.Token // where the runs' images are downloaded from
	c = conn.New(cfg, version, mgr.Probe)
	c.OnState = func(s string) { fmt.Fprintln(out, s) }

	err = mgr.Serve(ctx, c)
	if errors.Is(err, context.Canceled) {
		return nil
	}
	return err
}
