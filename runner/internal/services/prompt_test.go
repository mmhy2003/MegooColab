package services

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPromptSection(t *testing.T) {
	write := func(t *testing.T, dir, name, content string) {
		t.Helper()
		p := filepath.Join(dir, name)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	t.Run("sets", func(t *testing.T) {
		wt := t.TempDir()
		write(t, wt, "svc/compose.yml", "services: {}\n")
		write(t, wt, FileName, `[services.test]
description = "Postgres for the backend tests"
compose = ["svc/compose.yml"]
ports = ["DB_PORT"]

[services.e2e]
compose = ["svc/compose.yml"]
`)
		got, err := PromptSection(wt)
		if err != nil {
			t.Fatal(err)
		}
		want := "\n\n## Test services\nThis repository declares services for its checks in `megoocolab.toml`: `e2e`, `test` (Postgres for the backend tests). Run every command that needs them as `megoocolab-runner services run <name> -- <command>`. It starts this worktree's own containers on free ports, gives your command the variables the file defines, and removes the containers when the command ends. Do not start, stop or reuse the project's containers any other way, and never touch containers you did not start.\n"
		if got != want {
			t.Errorf("section =\n%q\nwant\n%q", got, want)
		}
	})

	t.Run("no file", func(t *testing.T) {
		got, err := PromptSection(t.TempDir())
		if got != "" || err != nil {
			t.Errorf("= %q, %v", got, err)
		}
	})

	t.Run("no sets", func(t *testing.T) {
		wt := t.TempDir()
		write(t, wt, FileName, "# nothing yet\n")
		got, err := PromptSection(wt)
		if got != "" || err != nil {
			t.Errorf("= %q, %v", got, err)
		}
	})

	t.Run("invalid file", func(t *testing.T) {
		wt := t.TempDir()
		write(t, wt, FileName, "[services.test]\ncompose = [\"missing.yml\"]\n")
		got, err := PromptSection(wt)
		if got != "" || err == nil {
			t.Errorf("= %q, %v", got, err)
		}
	})

	t.Run("only the worktree's own file", func(t *testing.T) {
		parent := t.TempDir()
		write(t, parent, "svc/compose.yml", "services: {}\n")
		write(t, parent, FileName, "[services.test]\ncompose = [\"svc/compose.yml\"]\n")
		wt := filepath.Join(parent, "wt")
		if err := os.Mkdir(wt, 0o755); err != nil {
			t.Fatal(err)
		}
		got, err := PromptSection(wt)
		if got != "" || err != nil {
			t.Errorf("= %q, %v", got, err)
		}
	})
}
