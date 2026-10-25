//go:build !windows

package cmd

import (
	"os"

	"github.com/kardianos/service"
)

type noopProgram struct{}

func (noopProgram) Start(service.Service) error { return nil }
func (noopProgram) Stop(service.Service) error  { return nil }

type libManager struct{ svc service.Service }

func newServiceManager() (serviceManager, error) {
	s, err := service.New(noopProgram{}, serviceConfig(os.Getenv("PATH")))
	if err != nil {
		return nil, err
	}
	return libManager{s}, nil
}

// Install replaces an existing installation, so re-running it refreshes the
// captured PATH.
func (m libManager) Install() error {
	if st, err := kardianosStatus(m.svc); err == nil && st != "not installed" {
		if st == "running" {
			_ = m.svc.Stop()
		}
		if err := m.svc.Uninstall(); err != nil {
			return err
		}
	}
	return m.svc.Install()
}
func (m libManager) Uninstall() error { return m.svc.Uninstall() }
func (m libManager) Start() error     { return m.svc.Start() }
func (m libManager) Stop() error      { return m.svc.Stop() }
func (m libManager) Status() (string, error) {
	return kardianosStatus(m.svc)
}
