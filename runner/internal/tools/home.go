package tools

import (
	"os"
	"path/filepath"
)

// Home is the user's home folder, where the agent programs keep their user-level setup.
func Home() (string, error) { return os.UserHomeDir() }

// CodexHome is where Codex keeps its config: $CODEX_HOME when set, else <home>/.codex.
func CodexHome(home string) string {
	if dir := os.Getenv("CODEX_HOME"); dir != "" {
		return dir
	}
	return filepath.Join(home, ".codex")
}
