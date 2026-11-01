package tools

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestWriteFileAtomicPrivate(t *testing.T) {
	home := isolate(t)
	path := filepath.Join(home, "sub", "secret.json")
	if err := WriteFileAtomic(path, []byte(`{"k":"v"}`), true); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil || string(data) != `{"k":"v"}` {
		t.Fatalf("read back %q, %v", data, err)
	}
	if runtime.GOOS != "windows" {
		info, _ := os.Stat(path)
		if info.Mode().Perm() != 0o600 {
			t.Fatalf("mode = %v, want 0600", info.Mode().Perm())
		}
	} else if err := MakePrivate(path); err != nil {
		t.Fatalf("MakePrivate: %v", err)
	}
	entries, _ := os.ReadDir(filepath.Dir(path))
	if len(entries) != 1 {
		t.Fatalf("left behind: %v", entries)
	}
}

func TestReplaceFileMissingFileStartsEmpty(t *testing.T) {
	home := isolate(t)
	path := filepath.Join(home, "new.txt")
	err := ReplaceFile(path, func(old []byte) ([]byte, error) {
		if old != nil {
			t.Fatalf("old = %q, want nil", old)
		}
		return []byte("first"), nil
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	if data, _ := os.ReadFile(path); string(data) != "first" {
		t.Fatalf("got %q", data)
	}
}

func TestReplaceFileRetriesOnConcurrentChange(t *testing.T) {
	home := isolate(t)
	path := filepath.Join(home, "conf.txt")
	if err := os.WriteFile(path, []byte("base\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	calls := 0
	err := ReplaceFile(path, func(old []byte) ([]byte, error) {
		calls++
		if calls == 1 { // someone else writes the file while we are editing it
			if err := os.WriteFile(path, []byte("base\nexternal-change\n"), 0o600); err != nil {
				t.Fatal(err)
			}
		}
		return append(append([]byte{}, old...), "ours\n"...), nil
	}, true)
	if err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(path)
	if calls != 2 || !strings.Contains(string(data), "external-change") || !strings.Contains(string(data), "ours") {
		t.Fatalf("calls=%d data=%q", calls, data)
	}
}
