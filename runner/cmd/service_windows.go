//go:build windows

package cmd

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

// Windows has no per-user service that needs no admin rights, and the runner
// installs no admin service. It is started at logon through the HKCU Run key
// and controlled through a pid file and a stop-request file (see
// service_proc.go). The Run key starts a launcher that starts a hidden
// supervisor; the supervisor owns the pid file and restarts the worker (the
// runner itself) with backoff after a crash (see supervise.go).

const runKeyPath = `Software\Microsoft\Windows\CurrentVersion\Run`

// startupApprovedPath holds what Task Manager → Startup apps records about
// the Run entries; a value here can disable the runner's entry.
const startupApprovedPath = `Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run`

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

// runValueRead returns the Run value, and false when the key or the value
// does not exist.
func (m winManager) runValueRead() (string, bool, error) {
	k, err := registry.OpenKey(registry.CURRENT_USER, runKeyPath, registry.QUERY_VALUE)
	if errors.Is(err, registry.ErrNotExist) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	defer k.Close()
	v, _, err := k.GetStringValue(runKeyValueName)
	if errors.Is(err, registry.ErrNotExist) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return v, true, nil
}

// startupApprovedBytes returns the entry's StartupApproved\Run value, or nil
// when it cannot be read (a missing value means enabled).
func (m winManager) startupApprovedBytes() []byte {
	k, err := registry.OpenKey(registry.CURRENT_USER, startupApprovedPath, registry.QUERY_VALUE)
	if err != nil {
		return nil
	}
	defer k.Close()
	b, _, err := k.GetBinaryValue(runKeyValueName)
	if err != nil {
		return nil
	}
	return b
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
	return pid, alive && sameFile(image, m.exe)
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

// Install stops a running runner, so the new binary replaces it, writes the
// Run value and re-enables the entry if it was disabled in Task Manager.
func (m winManager) Install() error {
	if err := m.Stop(); err != nil {
		return err
	}
	k, _, err := registry.CreateKey(registry.CURRENT_USER, runKeyPath, registry.SET_VALUE)
	if err != nil {
		return err
	}
	defer k.Close()
	if err := k.SetStringValue(runKeyValueName, runValue(m.exe)); err != nil {
		return err
	}
	a, err := registry.OpenKey(registry.CURRENT_USER, startupApprovedPath, registry.SET_VALUE)
	if err != nil {
		return nil // no StartupApproved key: nothing is disabled
	}
	defer a.Close()
	if err := a.DeleteValue(runKeyValueName); err != nil && !errors.Is(err, registry.ErrNotExist) {
		return err
	}
	return nil
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
	if err := spawnHidden(m.exe, "run", "--background"); err != nil {
		return err
	}
	for i := 0; i < 30; i++ {
		time.Sleep(100 * time.Millisecond)
		if _, ok := m.runningPID(); ok {
			return nil
		}
	}
	return fmt.Errorf("the runner did not start; see %s", logPath(m.root))
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
	if image, alive := processImage(pid); !alive || !sameFile(image, m.exe) {
		return nil
	}
	// Kill the whole tree (adapters and their children), not just the runner.
	_ = exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(pid)).Run()
	if h, err := windows.OpenProcess(windows.PROCESS_TERMINATE, false, uint32(pid)); err == nil {
		_ = windows.TerminateProcess(h, 1)
		windows.CloseHandle(h)
	}
	_ = os.Remove(pidPath(m.root))
	return nil
}

func (m winManager) Status() (string, error) {
	value, installed, err := m.runValueRead()
	if err != nil {
		return "", fmt.Errorf("cannot read the Run key: %w", err)
	}
	pid, running := m.runningPID()
	lines := []string{statusText(installed, running, pid)}
	if installed {
		lines = append(lines, autostartLines(value, fileExists, startupDisabled(m.startupApprovedBytes()))...)
	}
	return strings.Join(lines, "\n"), nil
}

// hiddenCmd builds a command that runs exe with a hidden console of its own
// and relaunchEnv set to marker (exec keeps the last of duplicate keys).
// CREATE_NO_WINDOW gives the process a console without a window that its
// children (git, node) inherit; adding DETACHED_PROCESS would cancel that and
// every child would pop up its own console window.
func hiddenCmd(exe, marker string, args ...string) *exec.Cmd {
	cmd := exec.Command(exe, args...)
	cmd.Env = append(os.Environ(), relaunchEnv+"="+marker)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: windows.CREATE_NO_WINDOW | windows.CREATE_NEW_PROCESS_GROUP,
		HideWindow:    true,
	}
	return cmd
}

// spawnHidden starts exe hidden as a supervisor and does not wait for it.
func spawnHidden(exe string, args ...string) error {
	cmd := hiddenCmd(exe, "1", args...)
	if err := cmd.Start(); err != nil {
		return err
	}
	return cmd.Process.Release()
}

// spawnSupervisor is what the launcher (started by the Run key) does: the Run
// key is the only thing that starts `run --background` without the marker, so
// it always relaunches hidden, whatever console it was given (a conhost window
// or a Windows Terminal tab).
func spawnSupervisor(exe string) error { return spawnHidden(exe, "run", "--background") }

// runWorkerProcess returns the supervisor's runWorker: it runs the worker
// hidden with stdout and stderr on logf (discarded when logf is nil, so a
// panic lands in runner.log) and returns its exit code.
func runWorkerProcess(exe string, logf *os.File) func() (int, error) {
	return func() (int, error) {
		cmd := hiddenCmd(exe, workerMarker, "run", "--background")
		if logf != nil {
			cmd.Stdout = logf
			cmd.Stderr = logf
		}
		if err := cmd.Start(); err != nil {
			return 0, err
		}
		err := cmd.Wait()
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return ee.ExitCode(), nil
		}
		return 0, err
	}
}

// otherRunnerPID reports a live runner that owns the pid file.
func otherRunnerPID(root, exe string) (int, bool) {
	return winManager{exe: exe, root: root}.runningPID()
}
