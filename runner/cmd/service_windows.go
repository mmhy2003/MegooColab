//go:build windows

package cmd

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

// Windows has no per-user service that needs no admin rights, so the runner is
// started at logon through the HKCU Run key and controlled through a pid file
// and a stop-request file (see service_proc.go). There is no crash restart:
// it comes back at the next logon or with `service start`.

const runKeyPath = `Software\Microsoft\Windows\CurrentVersion\Run`

type winManager struct {
	exe  string
	root string
}

func newServiceManager() (serviceManager, error) {
	exe, err := os.Executable()
	if err != nil {
		return nil, err
	}
	root, err := cacheRoot()
	if err != nil {
		return nil, err
	}
	return winManager{exe: exe, root: root}, nil
}

func (m winManager) installed() (bool, error) {
	k, err := registry.OpenKey(registry.CURRENT_USER, runKeyPath, registry.QUERY_VALUE)
	if errors.Is(err, registry.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	defer k.Close()
	_, _, err = k.GetStringValue(runKeyValueName)
	if errors.Is(err, registry.ErrNotExist) {
		return false, nil
	}
	return err == nil, err
}

// runningPID returns the pid in the pid file when that process is alive and is
// this runner's executable (a reused pid belongs to another program).
func (m winManager) runningPID() (int, bool) {
	b, err := os.ReadFile(pidPath(m.root))
	if err != nil {
		return 0, false
	}
	pid, ok := parsePID(b)
	if !ok {
		return 0, false
	}
	image, alive := processImage(pid)
	return pid, alive && sameImage(image, m.exe)
}

func processImage(pid int) (string, bool) {
	h, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return "", false
	}
	defer windows.CloseHandle(h)
	var code uint32
	if err := windows.GetExitCodeProcess(h, &code); err != nil || code != 259 { // STILL_ACTIVE
		return "", false
	}
	buf := make([]uint16, windows.MAX_PATH*4)
	n := uint32(len(buf))
	if err := windows.QueryFullProcessImageName(h, 0, &buf[0], &n); err != nil {
		return "", false
	}
	return windows.UTF16ToString(buf[:n]), true
}

func (m winManager) Install() error {
	k, _, err := registry.CreateKey(registry.CURRENT_USER, runKeyPath, registry.SET_VALUE)
	if err != nil {
		return err
	}
	defer k.Close()
	return k.SetStringValue(runKeyValueName, runValue(m.exe))
}

func (m winManager) Uninstall() error {
	if err := m.Stop(); err != nil {
		return err
	}
	k, err := registry.OpenKey(registry.CURRENT_USER, runKeyPath, registry.SET_VALUE)
	if errors.Is(err, registry.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	defer k.Close()
	if err := k.DeleteValue(runKeyValueName); err != nil && !errors.Is(err, registry.ErrNotExist) {
		return err
	}
	return nil
}

func (m winManager) Start() error {
	if pid, ok := m.runningPID(); ok {
		return fmt.Errorf("already running (pid %d)", pid)
	}
	_ = os.Remove(pidPath(m.root))
	_ = os.Remove(stopPath(m.root))
	cmd := exec.Command(m.exe, "run", "--background")
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: windows.CREATE_NO_WINDOW | windows.DETACHED_PROCESS | windows.CREATE_NEW_PROCESS_GROUP,
		HideWindow:    true,
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	_ = cmd.Process.Release()
	for i := 0; i < 30; i++ {
		time.Sleep(100 * time.Millisecond)
		if _, ok := m.runningPID(); ok {
			return nil
		}
	}
	return errors.New("the runner did not start; run `megoocolab-runner run` in a terminal to see why")
}

func (m winManager) Stop() error {
	pid, ok := m.runningPID()
	if !ok {
		_ = os.Remove(pidPath(m.root))
		return nil
	}
	if err := os.WriteFile(stopPath(m.root), nil, 0o600); err != nil {
		return err
	}
	defer os.Remove(stopPath(m.root))
	for i := 0; i < 150; i++ {
		if _, ok := m.runningPID(); !ok {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	// Graceful stop timed out. Kill only if the pid is still this runner.
	if image, alive := processImage(pid); !alive || !sameImage(image, m.exe) {
		return nil
	}
	h, err := windows.OpenProcess(windows.PROCESS_TERMINATE, false, uint32(pid))
	if err != nil {
		return err
	}
	defer windows.CloseHandle(h)
	if err := windows.TerminateProcess(h, 1); err != nil {
		return err
	}
	_ = os.Remove(pidPath(m.root))
	return nil
}

func (m winManager) Status() (string, error) {
	installed, err := m.installed()
	if err != nil {
		return "", fmt.Errorf("cannot read the Run key: %w", err)
	}
	pid, running := m.runningPID()
	return statusText(installed, running, pid), nil
}
