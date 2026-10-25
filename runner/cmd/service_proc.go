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

func parsePID(b []byte) (int, bool) {
	pid, err := strconv.Atoi(strings.TrimSpace(string(b)))
	return pid, err == nil && pid > 0
}

// sameImage compares two executable paths the way Windows does.
func sameImage(a, b string) bool {
	return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
}

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
	return func() { _ = os.Remove(pidPath(root)) }, nil
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
