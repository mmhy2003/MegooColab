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
	return buildOnce(t, &fakeOnce, &fakePath, &fakeErr, "./internal/fakeagent", "fakeagent")
}

var (
	gitOnce sync.Once
	gitPath string
	gitErr  error
)

// BuildFakeGit is BuildFakeAgent for ./internal/fakegit.
func BuildFakeGit(t testing.TB) string {
	t.Helper()
	return buildOnce(t, &gitOnce, &gitPath, &gitErr, "./internal/fakegit", "fakegit")
}

var (
	dockerOnce sync.Once
	dockerPath string
	dockerErr  error
)

// BuildFakeDocker compiles ./internal/fakedocker as docker (docker.exe on
// Windows) and returns the folder holding it, to put first on PATH.
func BuildFakeDocker(t testing.TB) string {
	t.Helper()
	return filepath.Dir(buildOnce(t, &dockerOnce, &dockerPath, &dockerErr, "./internal/fakedocker", "docker"))
}

var (
	runnerOnce sync.Once
	runnerPath string
	runnerErr  error
)

// BuildRunner compiles the runner itself and returns the executable path.
func BuildRunner(t testing.TB) string {
	t.Helper()
	return buildOnce(t, &runnerOnce, &runnerPath, &runnerErr, ".", "megoocolab-runner")
}

// buildOnce builds pkg (relative to the runner module root) as outName, plus
// .exe on Windows.
func buildOnce(t testing.TB, once *sync.Once, path *string, berr *error, pkg, outName string) string {
	t.Helper()
	once.Do(func() {
		dir, err := os.MkdirTemp("", outName+"-")
		if err != nil {
			*berr = err
			return
		}
		name := outName
		if runtime.GOOS == "windows" {
			name += ".exe"
		}
		out := filepath.Join(dir, name)
		_, file, _, _ := runtime.Caller(0)
		root := filepath.Join(filepath.Dir(file), "..", "..") // runner module root
		cmd := exec.Command("go", "build", "-o", out, pkg)
		cmd.Dir = root
		if b, err := cmd.CombinedOutput(); err != nil {
			*berr = &buildError{err: err, out: string(b)}
			return
		}
		*path = out
	})
	if *berr != nil {
		t.Fatalf("build %s: %v", pkg, *berr)
	}
	return *path
}

type buildError struct {
	err error
	out string
}

func (e *buildError) Error() string { return e.err.Error() + "\n" + e.out }
