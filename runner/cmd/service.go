package cmd

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/kardianos/service"
	"github.com/spf13/cobra"
)

const (
	serviceName = "megoocolab-runner"
	maxLogBytes = 5 << 20
)

// serviceConfig describes the background service. It is a pure function so it
// can be tested without touching the real service manager. The service runs as
// the current user (systemd --user, launchd LaunchAgent) because the agent
// adapters need that user's logins and repositories.
func serviceConfig() *service.Config {
	return &service.Config{
		Name:        serviceName,
		DisplayName: "MegooColab Runner",
		Description: "Runs coding agents on this machine for MegooColab.",
		Arguments:   []string{"run"},
		Option:      service.KeyValue{"UserService": true},
	}
}

// serviceManager is the per-platform way of registering and controlling the
// background runner.
type serviceManager interface {
	Install() error
	Uninstall() error
	Start() error
	Stop() error
	// Status returns "running", "stopped" or "not installed".
	Status() (string, error)
}

func newServiceCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "service",
		Short: "Install and control the runner as a background service for the current user",
	}
	actions := []struct {
		name, short string
		do          func(serviceManager) error
	}{
		{"install", "Register the runner to start in the background (no admin rights needed)", serviceManager.Install},
		{"uninstall", "Remove the background service", serviceManager.Uninstall},
		{"start", "Start the background service", serviceManager.Start},
		{"stop", "Stop the background service", serviceManager.Stop},
	}
	for _, a := range actions {
		a := a
		cmd.AddCommand(&cobra.Command{
			Use:   a.name,
			Short: a.short,
			Args:  cobra.NoArgs,
			RunE: func(c *cobra.Command, _ []string) error {
				m, err := newServiceManager()
				if err != nil {
					return err
				}
				if err := a.do(m); err != nil {
					return fmt.Errorf("service %s: %w", a.name, err)
				}
				fmt.Fprintf(c.OutOrStdout(), "service %s: ok\n", a.name)
				return nil
			},
		})
	}
	cmd.AddCommand(&cobra.Command{
		Use:   "status",
		Short: "Show whether the background service is running",
		Args:  cobra.NoArgs,
		RunE: func(c *cobra.Command, _ []string) error {
			m, err := newServiceManager()
			if err != nil {
				return err
			}
			s, err := m.Status()
			if err != nil {
				return err
			}
			fmt.Fprintln(c.OutOrStdout(), s)
			return nil
		},
	})
	return cmd
}

// kardianosStatus maps the library status to the words the CLI prints.
func kardianosStatus(s service.Service) (string, error) {
	st, err := s.Status()
	if errors.Is(err, service.ErrNotInstalled) {
		return "not installed", nil
	}
	if err != nil {
		return "", err
	}
	if st == service.StatusRunning {
		return "running", nil
	}
	return "stopped", nil
}

// openRunLog opens <cacheRoot>/logs/runner.log for appending. A log larger
// than maxLogBytes is truncated first, which keeps rotation trivial.
func openRunLog(cacheRoot string) (io.WriteCloser, error) {
	dir := filepath.Join(cacheRoot, "logs")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	path := filepath.Join(dir, "runner.log")
	flags := os.O_CREATE | os.O_WRONLY | os.O_APPEND
	if fi, err := os.Stat(path); err == nil && fi.Size() > maxLogBytes {
		flags = os.O_CREATE | os.O_WRONLY | os.O_TRUNC
	}
	return os.OpenFile(path, flags, 0o600)
}
