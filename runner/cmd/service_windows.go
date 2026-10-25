//go:build windows

package cmd

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strconv"
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
	if err := spawnHidden(m.exe, "run", "--background"); err != nil {
		return err
	}
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
	installed, err := m.installed()
	if err != nil {
		return "", fmt.Errorf("cannot read the Run key: %w", err)
	}
	pid, running := m.runningPID()
	return statusText(installed, running, pid), nil
}

// spawnHidden starts exe with a hidden console of its own. CREATE_NO_WINDOW
// gives the process a console without a window that its children (git, node)
// inherit; adding DETACHED_PROCESS would cancel that and every child would pop
// up its own console window.
func spawnHidden(exe string, args ...string) error {
	cmd := exec.Command(exe, args...)
	cmd.Env = append(os.Environ(), relaunchEnv+"=1")
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: windows.CREATE_NO_WINDOW | windows.CREATE_NEW_PROCESS_GROUP,
		HideWindow:    true,
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	return cmd.Process.Release()
}

var (
	kernel32         = windows.NewLazySystemDLL("kernel32.dll")
	user32           = windows.NewLazySystemDLL("user32.dll")
	procConsoleWnd   = kernel32.NewProc("GetConsoleWindow")
	procIsWindowVisi = user32.NewProc("IsWindowVisible")
)

// relaunchHiddenIfNeeded is called first by `run --background`. The Run key
// starts the console exe with a visible console window (closing it would kill
// the runner), so restart once without one and let this process exit. The
// child carries relaunchEnv and never relaunches.
func relaunchHiddenIfNeeded() (bool, error) {
	hwnd, _, _ := procConsoleWnd.Call()
	visible := false
	if hwnd != 0 {
		r, _, _ := procIsWindowVisi.Call(hwnd)
		visible = r != 0
	}
	if !shouldRelaunchHidden(os.Getenv(relaunchEnv), visible) {
		return false, nil
	}
	exe, err := os.Executable()
	if err != nil {
		return false, err
	}
	return true, spawnHidden(exe, os.Args[1:]...)
}
