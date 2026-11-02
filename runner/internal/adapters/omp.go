package adapters

import (
	"regexp"
	"strconv"
)

// OmpMinVersion is the oldest OMP that can run agents: the first with ACP steering (_session/steering).
const OmpMinVersion = "18.12.6"

var semver = regexp.MustCompile(`(\d+)\.(\d+)\.(\d+)`)

// OmpProblem is what stops OMP agents on this machine ("" when nothing does): omp missing, not startable, or
// older than OmpMinVersion. version runs `<path> --version`. With MEGOO_ADAPTER_OMP set the override replaces
// omp, so nothing is checked.
func OmpProblem(goos string, getenv func(string) string, lookPath func(string) (string, error),
	version func(path string) (string, error)) string {
	if getenv("MEGOO_ADAPTER_OMP") != "" {
		return ""
	}
	path, err := lookPath("omp")
	if err != nil {
		// a PowerShell shim (npm's omp.ps1) is on PATH, but no process can start it
		if goos == "windows" {
			if _, err := lookPath("omp.ps1"); err == nil {
				return "omp found but cannot be started; reinstall with the OMP installer"
			}
		}
		return "omp not found"
	}
	out, err := version(path)
	if err != nil || !atLeast(out, OmpMinVersion) {
		return "OMP " + OmpMinVersion + " or newer is needed"
	}
	return ""
}

// atLeast reports whether the first x.y.z in out is min or newer.
func atLeast(out, min string) bool {
	got, want := semver.FindStringSubmatch(out), semver.FindStringSubmatch(min)
	if got == nil {
		return false
	}
	for i := 1; i <= 3; i++ {
		g, _ := strconv.Atoi(got[i])
		w, _ := strconv.Atoi(want[i])
		if g != w {
			return g > w
		}
	}
	return true
}
