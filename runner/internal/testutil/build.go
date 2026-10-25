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
	return buildOnce(t, &fakeOnce, &fakePath, &fakeErr, "fakeagent")
}

var (
	gitOnce sync.Once
	gitPath string
	gitErr  error
)

// BuildFakeGit is BuildFakeAgent for ./internal/fakegit.
func BuildFakeGit(t testing.TB) string {
	t.Helper()
	return buildOnce(t, &gitOnce, &gitPath, &gitErr, "fakegit")
}

func buildOnce(t testing.TB, once *sync.Once, path *string, berr *error, cmdName string) string {
	t.Helper()
	once.Do(func() {
		dir, err := os.MkdirTemp("", cmdName+"-")
		if err != nil {
			*berr = err
			return
		}
		name := cmdName
		if runtime.GOOS == "windows" {
			name += ".exe"
		}
		out := filepath.Join(dir, name)
		_, file, _, _ := runtime.Caller(0)
		root := filepath.Join(filepath.Dir(file), "..", "..") // runner module root
		cmd := exec.Command("go", "build", "-o", out, "./internal/"+cmdName)
		cmd.Dir = root
		if b, err := cmd.CombinedOutput(); err != nil {
			*berr = &buildError{err: err, out: string(b)}
			return
		}
		*path = out
	})
	if *berr != nil {
		t.Fatalf("build %s: %v", cmdName, *berr)
	}
	return *path
}

type buildError struct {
	err error
	out string
}

func (e *buildError) Error() string { return e.err.Error() + "\n" + e.out }
