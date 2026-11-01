package tools

import (
	"path/filepath"
	"testing"
)

// isolate points every home and config folder the tools package may touch at a temporary folder, so a test
// never writes into the real ~/.claude.json, ~/.codex or the runner's own config.
func isolate(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	config := filepath.Join(home, "config")
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("APPDATA", config)
	t.Setenv("XDG_CONFIG_HOME", config)
	t.Setenv("CODEX_HOME", "")
	return home
}
