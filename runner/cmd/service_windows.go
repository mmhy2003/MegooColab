//go:build windows

package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
)

type taskManager struct{ exe string }

func newServiceManager() (serviceManager, error) {
	exe, err := os.Executable()
	if err != nil {
		return nil, err
	}
	return taskManager{exe: exe}, nil
}

func schtasks(args ...string) (string, error) {
	out, err := exec.Command("schtasks", args...).CombinedOutput()
	if err != nil {
		return string(out), fmt.Errorf("schtasks %s: %w: %s", args[0], err, strings.TrimSpace(string(out)))
	}
	return string(out), nil
}

func (m taskManager) Install() error {
	_, err := schtasks(taskCreateArgs(m.exe)...)
	return err
}
func (m taskManager) Uninstall() error {
	_, err := schtasks(append(taskArgs("/Delete"), "/F")...)
	return err
}
func (m taskManager) Start() error { _, err := schtasks(taskArgs("/Run")...); return err }
func (m taskManager) Stop() error  { _, err := schtasks(taskArgs("/End")...); return err }
func (m taskManager) Status() (string, error) {
	out, err := schtasks("/Query", "/TN", serviceName, "/FO", "LIST", "/V")
	if err != nil {
		return "not installed", nil
	}
	return parseTaskStatus(out), nil
}
