package cmd

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
)

// stubLoadConfig makes loadConfig fail with os.ErrNotExist for one test.
func stubLoadConfig(t *testing.T) {
	t.Helper()
	orig := loadConfig
	t.Cleanup(func() { loadConfig = orig })
	loadConfig = func() (config.Config, error) { return config.Config{}, os.ErrNotExist }
}

// logLines reads path and checks that every line starts with an RFC 3339
// timestamp.
func logLines(t *testing.T, path string) []string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	lines := strings.Split(strings.TrimRight(string(b), "\n"), "\n")
	for _, l := range lines {
		ts, _, _ := strings.Cut(l, " ")
		if _, err := time.Parse(time.RFC3339, ts); err != nil {
			t.Errorf("line %q does not start with a timestamp: %v", l, err)
		}
	}
	return lines
}

func hasLine(lines []string, match func(string) bool) bool {
	for _, l := range lines {
		if match(l) {
			return true
		}
	}
	return false
}

var startLine = regexp.MustCompile(`^\S+ starting megoocolab-runner 9\.9\.9 \(pid \d+\)$`)

func TestRunServiceLogsMissingConfig(t *testing.T) {
	stubLoadConfig(t)
	root := t.TempDir()
	err := runServiceAt(context.Background(), roleSingle, "9.9.9", root, nil, t.TempDir())
	if !errors.Is(err, errNotLoggedIn) {
		t.Fatalf("err = %v, want errNotLoggedIn", err)
	}
	lines := logLines(t, logPath(root))
	if !hasLine(lines, startLine.MatchString) {
		t.Errorf("no starting line in %q", lines)
	}
	if !hasLine(lines, func(l string) bool { return strings.Contains(l, " error: not logged in") }) {
		t.Errorf("no error line in %q", lines)
	}
}

func TestRunServiceFallbackLogOnCacheError(t *testing.T) {
	tempDir := t.TempDir()
	rootErr := errors.New("no cache dir")
	err := runServiceAt(context.Background(), roleSingle, "9.9.9", "", rootErr, tempDir)
	if !errors.Is(err, rootErr) {
		t.Fatalf("err = %v, want %v", err, rootErr)
	}
	lines := logLines(t, filepath.Join(tempDir, fallbackLogName))
	if !hasLine(lines, startLine.MatchString) {
		t.Errorf("no starting line in %q", lines)
	}
	if !hasLine(lines, func(l string) bool { return strings.HasSuffix(l, " error: no cache dir") }) {
		t.Errorf("no error line in %q", lines)
	}
}

func TestRunServiceWorkerErrorIsQuiet(t *testing.T) {
	stubLoadConfig(t)
	// A worker logs to stderr, which its supervisor points at runner.log.
	stderr, err := os.Create(filepath.Join(t.TempDir(), "stderr.log"))
	if err != nil {
		t.Fatal(err)
	}
	defer stderr.Close()
	orig := os.Stderr
	os.Stderr = stderr
	t.Cleanup(func() { os.Stderr = orig })

	err = runServiceAt(context.Background(), roleWorker, "9.9.9", t.TempDir(), nil, t.TempDir())
	var q quietError
	if !errors.As(err, &q) {
		t.Fatalf("err = %v (%T), want a quietError", err, err)
	}
	if got := exitCode(err, "linux", false); got != 78 {
		t.Errorf("exitCode = %d, want 78", got)
	}
	lines := logLines(t, stderr.Name())
	if !hasLine(lines, func(l string) bool { return strings.Contains(l, " error: not logged in") }) {
		t.Errorf("no error line in %q", lines)
	}
}
