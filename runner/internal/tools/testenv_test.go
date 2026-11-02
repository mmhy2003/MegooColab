package tools

import (
	"errors"
	"path/filepath"
	"testing"
)

// isolate points every home and config folder the tools package may touch at a temporary folder, so a test
// never writes into the real ~/.claude.json, ~/.codex, ~/.omp or the runner's own config.
func isolate(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	config := filepath.Join(home, "config")
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("APPDATA", config)
	t.Setenv("XDG_CONFIG_HOME", config)
	t.Setenv("CODEX_HOME", "")
	for _, k := range []string{"PI_CONFIG_DIR", "OMP_PROFILE", "PI_PROFILE", "PI_CODING_AGENT_DIR"} {
		t.Setenv(k, "")
	}
	// an omp installed on the machine must not decide where a test writes
	old := ompConfigPath
	ompConfigPath = func() (string, error) { return "", errors.New("omp is not run in tests") }
	t.Cleanup(func() { ompConfigPath = old })
	return home
}
