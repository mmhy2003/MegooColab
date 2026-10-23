// Package testutil holds helpers shared by the runner's tests.
package testutil

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync"
	"testing"
)

var (
	fakeOnce sync.Once
	fakePath string
	fakeErr  error
)

// BuildFakeAgent compiles ./internal/fakeagent once per test binary run and
// returns the executable path. The binary lives in a temp dir that is not
// removed (there is no per-binary teardown hook outside TestMain).
func BuildFakeAgent(t testing.TB) string {
	t.Helper()
	fakeOnce.Do(func() {
		dir, err := os.MkdirTemp("", "fakeagent-")
		if err != nil {
			fakeErr = err
			return
		}
		name := "fakeagent"
		if runtime.GOOS == "windows" {
			name += ".exe"
		}
		out := filepath.Join(dir, name)
		_, file, _, _ := runtime.Caller(0)
		root := filepath.Join(filepath.Dir(file), "..", "..") // runner module root
		cmd := exec.Command("go", "build", "-o", out, "./internal/fakeagent")
		cmd.Dir = root
		if b, err := cmd.CombinedOutput(); err != nil {
			fakeErr = &buildError{err: err, out: string(b)}
			return
		}
		fakePath = out
	})
	if fakeErr != nil {
		t.Fatalf("build fake agent: %v", fakeErr)
	}
	return fakePath
}

type buildError struct {
	err error
	out string
}

func (e *buildError) Error() string { return e.err.Error() + "\n" + e.out }
