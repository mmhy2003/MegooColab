package cmd

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestTSWriterPrefixesEachLine(t *testing.T) {
	now := time.Date(2026, 11, 16, 8, 30, 0, 0, time.Local)
	ts := now.Format(time.RFC3339) + " "
	cases := []struct {
		name   string
		writes []string
		want   string
	}{
		{"two lines", []string{"a\nb\n"}, ts + "a\n" + ts + "b\n"},
		{"partial line", []string{"par", "tial\n"}, ts + "partial\n"},
		{"line split across writes", []string{"x\ny", "z\n"}, ts + "x\n" + ts + "yz\n"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var buf bytes.Buffer
			w := newTSWriter(&buf, func() time.Time { return now })
			for _, s := range c.writes {
				n, err := w.Write([]byte(s))
				if err != nil || n != len(s) {
					t.Fatalf("Write(%q) = %d, %v", s, n, err)
				}
			}
			if got := buf.String(); got != c.want {
				t.Fatalf("got %q, want %q", got, c.want)
			}
		})
	}
}

func readFile(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func TestOpenServiceLogUsesRunnerLog(t *testing.T) {
	root := t.TempDir()
	f, path := openServiceLog(root, t.TempDir())
	if f == nil {
		t.Fatal("no log file")
	}
	if path != logPath(root) {
		t.Fatalf("path = %q, want %q", path, logPath(root))
	}
	if _, err := f.WriteString("started\n"); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	if got := readFile(t, path); !strings.Contains(got, "started\n") {
		t.Fatalf("runner.log = %q", got)
	}
}

func TestOpenServiceLogFallsBack(t *testing.T) {
	notDir := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(notDir, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	for name, root := range map[string]string{"no root": "", "root is a file": notDir} {
		t.Run(name, func(t *testing.T) {
			tmp := t.TempDir()
			f, path := openServiceLog(root, tmp)
			if f == nil {
				t.Fatal("no log file")
			}
			defer f.Close()
			if want := filepath.Join(tmp, fallbackLogName); path != want {
				t.Fatalf("path = %q, want %q", path, want)
			}
			if _, err := f.WriteString("config missing\n"); err != nil {
				t.Fatal(err)
			}
			if got := readFile(t, path); got != "config missing\n" {
				t.Fatalf("fallback log = %q", got)
			}
		})
	}
}

func TestOpenServiceLogGivesUp(t *testing.T) {
	notDir := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(notDir, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	f, path := openServiceLog("", filepath.Join(notDir, "tmp"))
	if f != nil {
		f.Close()
		t.Fatal("opened a log under a regular file")
	}
	if path != "" {
		t.Fatalf("path = %q, want empty", path)
	}
}
