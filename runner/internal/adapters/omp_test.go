package adapters

import (
	"errors"
	"reflect"
	"testing"
)

func okLook(s string) (string, error) { return "/bin/" + s, nil }

func noLook(string) (string, error) { return "", errors.New("not found") }

func version(out string) func(string) (string, error) {
	return func(string) (string, error) { return out, nil }
}

func TestForOmpStartsAcpWithAskingApprovals(t *testing.T) {
	for _, goos := range []string{"windows", "linux", "darwin"} {
		s, err := forOS(goos, Omp, noEnv, okLook)
		if err != nil {
			t.Fatal(err)
		}
		if s.Program != Omp || s.Command != "omp" || !reflect.DeepEqual(s.Args, []string{"acp", "--approval-mode", "always-ask"}) {
			t.Fatalf("%s: spec = %+v", goos, s)
		}
	}
}

func TestForOmpOverride(t *testing.T) {
	env := func(k string) string {
		if k == "MEGOO_ADAPTER_OMP" {
			return `"C:\fake agent.exe" --x`
		}
		return ""
	}
	s, err := forOS("windows", Omp, env, okLook)
	if err != nil {
		t.Fatal(err)
	}
	if s.Command != `C:\fake agent.exe` || !reflect.DeepEqual(s.Args, []string{"--x"}) {
		t.Fatalf("spec = %+v", s)
	}
}

func TestOmpProblemNotFound(t *testing.T) {
	for _, goos := range []string{"windows", "linux", "darwin"} {
		if got := OmpProblem(goos, noEnv, noLook, version("18.12.6")); got != "omp not found" {
			t.Errorf("%s: %q", goos, got)
		}
	}
}

func TestOmpProblemTooOld(t *testing.T) {
	if got := OmpProblem("linux", noEnv, okLook, version("omp 18.12.5")); got != "OMP 18.12.6 or newer is needed" {
		t.Fatalf("got %q", got)
	}
}

func TestOmpProblemFine(t *testing.T) {
	for _, out := range []string{"18.12.6", "omp v18.13.0 (bun)\n", "19.0.0", "18.100.1"} {
		if got := OmpProblem("darwin", noEnv, okLook, version(out)); got != "" {
			t.Errorf("%q: %q", out, got)
		}
	}
}

func TestOmpProblemUnreadableVersion(t *testing.T) {
	for _, out := range []string{"", "dev"} {
		if got := OmpProblem("linux", noEnv, okLook, version(out)); got != "OMP 18.12.6 or newer is needed" {
			t.Errorf("%q: %q", out, got)
		}
	}
	failing := func(string) (string, error) { return "", errors.New("exit 1") }
	if got := OmpProblem("linux", noEnv, okLook, failing); got != "OMP 18.12.6 or newer is needed" {
		t.Errorf("failed --version: %q", got)
	}
}

func TestOmpProblemPowerShellShimOnly(t *testing.T) {
	look := func(s string) (string, error) {
		if s == "omp.ps1" {
			return `C:\Users\me\AppData\Roaming\npm\omp.ps1`, nil
		}
		return "", errors.New("not found")
	}
	if got := OmpProblem("windows", noEnv, look, version("18.12.6")); got != "omp found but cannot be started; reinstall with the OMP installer" {
		t.Fatalf("got %q", got)
	}
	if got := OmpProblem("linux", noEnv, look, version("18.12.6")); got != "omp not found" {
		t.Fatalf("linux: %q", got)
	}
}

func TestOmpProblemSkippedWithOverride(t *testing.T) {
	env := func(k string) string {
		if k == "MEGOO_ADAPTER_OMP" {
			return "fakeagent"
		}
		return ""
	}
	look := func(string) (string, error) { t.Fatal("lookPath called"); return "", nil }
	if got := OmpProblem("linux", env, look, version("")); got != "" {
		t.Fatalf("got %q", got)
	}
}
