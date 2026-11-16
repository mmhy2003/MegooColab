package cmd

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/kardianos/service"
	"github.com/spf13/cobra"
)

const (
	serviceName = "megoocolab-runner"
	maxLogBytes = 5 << 20
)

// systemdUserScript is kardianos' systemd template with two changes: a user
// unit must be wanted by default.target, because user managers never reach
// multi-user.target and `systemctl --user enable` would not autostart it; and
// it is not restarted after the server ended the session for good (revoked
// token, replaced runner), which would otherwise loop every RestartSec.
const systemdUserScript = `[Unit]
Description={{Description}}
ConditionFileIsExecutable={{Path | cmdEscape}}
{{range Dependencies}}{{.}}
{{end}}
[Service]
StartLimitInterval=5
StartLimitBurst=10
ExecStart={{Path | cmdEscape}}{{range Arguments}} {{. | cmd}}{{end}}
{{if ChRoot}}RootDirectory={{ChRoot | cmd}}
{{end}}{{if WorkingDirectory}}WorkingDirectory={{WorkingDirectory | cmdEscape}}
{{end}}{{if UserName}}User={{UserName}}
{{end}}{{if ReloadSignal}}ExecReload=/bin/kill -{{ReloadSignal}} "$MAINPID"
{{end}}{{if PIDFile}}PIDFile={{PIDFile | cmd}}
{{end}}{{if OutputFileSupport}}StandardOutput=file:{{LogDirectory}}/{{Name}}.out
StandardError=file:{{LogDirectory}}/{{Name}}.err
{{end}}{{if LimitNOFILE}}LimitNOFILE={{LimitNOFILE}}
{{end}}{{if Restart}}Restart={{Restart}}
{{end}}{{if SuccessExitStatus}}SuccessExitStatus={{SuccessExitStatus}}
{{end}}RestartPreventExitStatus={{EXIT_STOPPED}}
RestartSec=120
EnvironmentFile=-/etc/sysconfig/{{Name}}

{{ENV}}[Install]
WantedBy=default.target
`

// serviceConfig describes the background service. It is a pure function so it
// can be tested without touching the real service manager. The service runs as
// the current user (systemd --user, launchd LaunchAgent) because the agent
// adapters need that user's logins and repositories. path is the PATH captured
// at install time: launchd and systemd --user start with a minimal PATH that
// would not find npx.
func serviceConfig(path string) *service.Config {
	script := strings.Replace(systemdUserScript, "{{ENV}}", systemdEnvLine(path), 1)
	script = strings.Replace(script, "{{EXIT_STOPPED}}", strconv.Itoa(exitStoppedByServer), 1)
	c := &service.Config{
		Name:        serviceName,
		DisplayName: "MegooColab Runner",
		Description: "Runs coding agents on this machine for MegooColab.",
		Arguments:   []string{"run"},
		Option: service.KeyValue{
			"UserService":   true,
			"SystemdScript": script,
		},
	}
	if path != "" {
		c.EnvVars = map[string]string{"PATH": path}
	}
	return c
}

// systemdEnvLine renders Environment="PATH=..." with systemd quoting
// (backslash, double quote and % escaped). kardianos writes its own EnvVars
// unquoted, which breaks on spaces, so systemd gets this line instead and
// EnvVars is left for launchd. A value containing the template delimiter is
// skipped rather than risk being parsed as template code.
func systemdEnvLine(path string) string {
	if path == "" || strings.Contains(path, "{{") {
		return ""
	}
	r := strings.NewReplacer(`\`, `\\`, `"`, `\"`, "%", "%%")
	return `Environment="PATH=` + r.Replace(path) + `"` + "\n\n"
}

// serviceManager is the per-platform way of registering and controlling the
// background runner.
type serviceManager interface {
	Install() error
	Uninstall() error
	Start() error
	Stop() error
	// Status describes the runner. Its first line is "running…", "stopped" or
	// "not installed"; Windows may add more lines.
	Status() (string, error)
}

func newServiceCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "service",
		Short: "Install and control the runner as a background service for the current user",
	}
	cmd.AddCommand(&cobra.Command{
		Use:   "install",
		Short: "Register the runner to start in the background and start it now (no admin rights needed)",
		Args:  cobra.NoArgs,
		RunE: func(c *cobra.Command, _ []string) error {
			m, err := newServiceManager()
			if err != nil {
				return err
			}
			return serviceInstall(m, c.OutOrStdout())
		},
	})
	cmd.AddCommand(&cobra.Command{
		Use:   "start",
		Short: "Start the background service",
		Args:  cobra.NoArgs,
		RunE: func(c *cobra.Command, _ []string) error {
			m, err := newServiceManager()
			if err != nil {
				return err
			}
			return serviceStart(m, c.OutOrStdout())
		},
	})
	actions := []struct {
		name, short string
		do          func(serviceManager) error
	}{
		{"uninstall", "Remove the background service", serviceManager.Uninstall},
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

// serviceInstall registers the runner, starts it and prints its status. It refuses
// before touching anything when `login` was not done.
func serviceInstall(m serviceManager, out io.Writer) error {
	if _, err := loadLogin(); err != nil {
		return fmt.Errorf("service install: %w", err)
	}
	if err := m.Install(); err != nil {
		return fmt.Errorf("service install: %w", err)
	}
	fmt.Fprintln(out, "service install: ok")
	if err := m.Start(); err != nil {
		return fmt.Errorf("service start: %w", err)
	}
	s, err := m.Status()
	if err != nil {
		return err
	}
	fmt.Fprintln(out, s)
	return nil
}

// serviceStart starts the runner; one that is already running is left alone, so
// `service install; service start` keeps working.
func serviceStart(m serviceManager, out io.Writer) error {
	if _, err := loadLogin(); err != nil {
		return fmt.Errorf("service start: %w", err)
	}
	if s, err := m.Status(); err == nil && strings.HasPrefix(s, "running") {
		fmt.Fprintln(out, "already running")
		return nil
	}
	if err := m.Start(); err != nil {
		return fmt.Errorf("service start: %w", err)
	}
	fmt.Fprintln(out, "service start: ok")
	return nil
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
func openRunLog(cacheRoot string) (*os.File, error) {
	path := logPath(cacheRoot)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	flags := os.O_CREATE | os.O_WRONLY | os.O_APPEND
	if fi, err := os.Stat(path); err == nil && fi.Size() > maxLogBytes {
		flags = os.O_CREATE | os.O_WRONLY | os.O_TRUNC
	}
	return os.OpenFile(path, flags, 0o600)
}
