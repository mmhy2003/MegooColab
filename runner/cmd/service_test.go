package cmd

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestServiceConfig(t *testing.T) {
	c := serviceConfig()
	if c.Name != "megoocolab-runner" {
		t.Errorf("Name = %q", c.Name)
	}
	if c.DisplayName != "MegooColab Runner" {
		t.Errorf("DisplayName = %q", c.DisplayName)
	}
	if v, ok := c.Option["UserService"].(bool); !ok || !v {
		t.Errorf("UserService option = %v, want true", c.Option["UserService"])
	}
	if !reflect.DeepEqual(c.Arguments, []string{"run"}) {
		t.Errorf("Arguments = %v", c.Arguments)
	}
}

func TestTaskCommands(t *testing.T) {
	create := taskCreateArgs(`C:\Users\me\bin\megoocolab-runner.exe`)
	joined := strings.Join(create, " ")
	for _, want := range []string{"/Create", "/SC ONLOGON", "/RL LIMITED", "/TN megoocolab-runner", "/F"} {
		if !strings.Contains(joined, want) {
			t.Errorf("create args %q missing %q", joined, want)
		}
	}
	if !strings.Contains(joined, `"C:\Users\me\bin\megoocolab-runner.exe" run --background`) {
		t.Errorf("create args do not quote the executable: %q", joined)
	}
	if got := taskArgs("/End"); !reflect.DeepEqual(got, []string{"/End", "/TN", "megoocolab-runner"}) {
		t.Errorf("taskArgs = %v", got)
	}
	if s := parseTaskStatus("HostName: X\r\nStatus:                                Running\r\n"); s != "running" {
		t.Errorf("status = %q", s)
	}
	if s := parseTaskStatus("Status: Ready"); s != "stopped" {
		t.Errorf("status = %q", s)
	}
}

func TestOpenRunLogTruncatesWhenLarge(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "logs", "runner.log")
	w, err := openRunLog(dir)
	if err != nil {
		t.Fatal(err)
	}
	w.Write([]byte("hello\n"))
	w.Close()
	w, _ = openRunLog(dir)
	w.Write([]byte("again\n"))
	w.Close()
	b, _ := os.ReadFile(path)
	if string(b) != "hello\nagain\n" {
		t.Fatalf("append failed: %q", b)
	}
	if err := os.WriteFile(path, make([]byte, maxLogBytes+1), 0o600); err != nil {
		t.Fatal(err)
	}
	w, _ = openRunLog(dir)
	w.Write([]byte("fresh\n"))
	w.Close()
	b, _ = os.ReadFile(path)
	if string(b) != "fresh\n" {
		t.Fatalf("not truncated: %d bytes", len(b))
	}
}
