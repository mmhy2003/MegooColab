package cmd

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// fallbackLogName is the start log in the temp directory, used when
// runner.log cannot be opened (no config yet, an unusable cache directory).
const fallbackLogName = "megoocolab-runner-start.log"

// tsWriter puts an RFC 3339 timestamp before every line written to w. Several
// goroutines write state lines, so writes are serialised.
type tsWriter struct {
	mu      sync.Mutex
	w       io.Writer
	now     func() time.Time
	midLine bool // the last write did not end with '\n'
}

func newTSWriter(w io.Writer, now func() time.Time) *tsWriter {
	return &tsWriter{w: w, now: now}
}

// Write writes p, putting now().Format(time.RFC3339) + " " before each line
// start. It returns len(p), nil unless the underlying write fails.
func (t *tsWriter) Write(p []byte) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	prefix := []byte(t.now().Format(time.RFC3339) + " ")
	var out bytes.Buffer
	start := !t.midLine
	for _, b := range p {
		if start {
			out.Write(prefix)
		}
		out.WriteByte(b)
		start = b == '\n'
	}
	if _, err := t.w.Write(out.Bytes()); err != nil {
		return 0, err
	}
	t.midLine = p[len(p)-1] != '\n'
	return len(p), nil
}

// logPath is the service log under the cache root.
func logPath(cacheRoot string) string {
	return filepath.Join(cacheRoot, "logs", "runner.log")
}

// openServiceLog opens runner.log under root. If root is "" or that fails, it
// opens <tempDir>/megoocolab-runner-start.log for appending. If both fail it
// returns (nil, ""): logging is best effort and never stops the runner.
func openServiceLog(root, tempDir string) (*os.File, string) {
	if root != "" {
		if f, err := openRunLog(root); err == nil {
			return f, logPath(root)
		}
	}
	path := filepath.Join(tempDir, fallbackLogName)
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return nil, ""
	}
	return f, path
}
