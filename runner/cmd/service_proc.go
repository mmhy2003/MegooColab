package cmd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Platform independent pieces of background mode. The Windows service manager
// (service_windows.go) is built on them: there is no per-user Windows service,
// so "service start" spawns `run --background` and talks to it through a pid
// file and a stop-request file in <cache>/megoocolab.

const runKeyValueName = serviceName

func pidPath(cacheRoot string) string  { return filepath.Join(cacheRoot, "runner.pid") }
func stopPath(cacheRoot string) string { return filepath.Join(cacheRoot, "runner.stop") }

func cacheRoot() (string, error) {
	dir, err := os.UserCacheDir()
	if err != nil {
		return "", fmt.Errorf("cannot find the cache directory: %w", err)
	}
	return filepath.Join(dir, "megoocolab"), nil
}

// runValue is the command line stored in the Windows Run key.
func runValue(exe string) string { return `"` + exe + `" run --background` }

// runValueExe returns the quoted executable at the start of a Run value, and
// false when the value has another shape.
func runValueExe(value string) (string, bool) {
	rest, ok := strings.CutPrefix(value, `"`)
	if !ok {
		return "", false
	}
	exe, _, ok := strings.Cut(rest, `"`)
	return exe, ok && exe != ""
}

// startupDisabled reports whether the entry's StartupApproved\Run value says
// it is disabled. Explorer stores 12 bytes there: an odd first byte (03) means
// disabled in Task Manager, an even one (02, 06) enabled, and a missing value
// means enabled.
func startupDisabled(b []byte) bool { return len(b) > 0 && b[0]%2 == 1 }

// autostartLines are the lines `service status` adds on Windows when the Run
// value exists: the stored command line, then why it would not start at logon.
func autostartLines(value string, exists func(string) bool, disabled bool) []string {
	lines := []string{"autostart: " + value}
	if exe, ok := runValueExe(value); ok && !exists(exe) {
		lines = append(lines, "warning: that file does not exist, so the runner will not start at logon; run `megoocolab-runner service install` again")
	}
	if disabled {
		lines = append(lines, "warning: the startup entry is disabled (Task Manager → Startup apps); enable it there or run `megoocolab-runner service install`")
	}
	return lines
}

func parsePID(b []byte) (int, bool) {
	pid, err := strconv.Atoi(strings.TrimSpace(string(b)))
	return pid, err == nil && pid > 0
}

// sameFile reports whether two paths are the same file. It compares file
// identity, not strings: Scoop runs the runner through a "current" junction
// while the OS reports the real path of a running image.
func sameFile(a, b string) bool {
	fa, err := os.Stat(a)
	if err != nil {
		return false
	}
	fb, err := os.Stat(b)
	if err != nil {
		return false
	}
	return os.SameFile(fa, fb)
}

// relaunchEnv carries the background role of a Windows `run --background`
// process (see backgroundRole).
const relaunchEnv = "MEGOOCOLAB_RUNNER_HIDDEN"

// workerMarker is the relaunchEnv value of the process the supervisor runs.
const workerMarker = "worker"

// bgRole is the part a `run` process plays in service mode.
type bgRole int

const (
	roleSingle     bgRole = iota // Linux, macOS, or no --background: one process, today's behaviour
	roleLauncher                 // Windows, marker unset: started by the Run key
	roleSupervisor               // Windows, marker "1": also what `service start` spawns
	roleWorker                   // Windows, marker "worker"
)

// backgroundRole picks the role of `run --background` from goos and the
// relaunchEnv marker. On Windows:
//
//	marker    role        what it does
//	unset     launcher    started by the Run key: starts the supervisor hidden
//	                      (CREATE_NO_WINDOW, marker "1") and exits 0
//	"1"       supervisor  writes the pid file and runs the worker in a loop,
//	                      restarting it with backoff
//	"worker"  worker      the runner itself: loads the config, connects and
//	                      watches the stop file; it never touches the pid file
//
// Linux and macOS have a service manager that restarts the runner, so there
// it is always a single process.
func backgroundRole(goos, marker string) bgRole {
	switch {
	case goos != "windows":
		return roleSingle
	case marker == "":
		return roleLauncher
	case marker == workerMarker:
		return roleWorker
	default:
		return roleSupervisor
	}
}

func fileExists(path string) bool { _, err := os.Stat(path); return err == nil }

func statusText(installed, running bool, pid int) string {
	switch {
	case running:
		return fmt.Sprintf("running (pid %d)", pid)
	case installed:
		return "stopped"
	default:
		return "not installed"
	}
}

// beginBackground is called by `run --background`: it clears a stale stop
// request, records the pid and returns the cleanup that removes the pid file.
func beginBackground(root string) (func(), error) {
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, err
	}
	if err := os.Remove(stopPath(root)); err != nil && !os.IsNotExist(err) {
		return nil, err
	}
	if err := os.WriteFile(pidPath(root), []byte(strconv.Itoa(os.Getpid())), 0o600); err != nil {
		return nil, err
	}
	// Remove the pid file only while it still holds our pid: another runner
	// may have overwritten it.
	return func() {
		if b, err := os.ReadFile(pidPath(root)); err == nil {
			if pid, ok := parsePID(b); ok && pid == os.Getpid() {
				_ = os.Remove(pidPath(root))
			}
		}
	}, nil
}

// watchStopFile calls cancel once path exists, or returns when ctx ends.
func watchStopFile(ctx context.Context, path string, every time.Duration, cancel context.CancelFunc) {
	t := time.NewTicker(every)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			if _, err := os.Stat(path); err == nil {
				cancel()
				return
			}
		}
	}
}
