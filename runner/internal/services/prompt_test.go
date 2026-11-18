package services

import (
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"testing"
)

func TestFormatNamesEveryKey(t *testing.T) {
	typ := reflect.TypeOf(setDoc{})
	for i := 0; i < typ.NumField(); i++ {
		tag := typ.Field(i).Tag.Get("toml")
		// A key's line is "- key:" or "- key (required):".
		line := regexp.MustCompile(`(?m)^- ` + regexp.QuoteMeta(tag) + `( \([^)]*\))?:`)
		if !line.MatchString(Format) {
			t.Errorf("Format does not describe the %q key", tag)
		}
	}
	for _, want := range []string{
		"[services.<name>]",
		"${NAME}",
		"MEGOO_SERVICES_",
		".env",
		"megoocolab-runner services run <name> -- <command>",
	} {
		if !strings.Contains(Format, want) {
			t.Errorf("Format does not contain %q", want)
		}
	}
}

func TestPromptSection(t *testing.T) {
	t.Run("sets", func(t *testing.T) {
		wt := t.TempDir()
		writeFile(t, wt, "svc/compose.yml", "services: {}\n")
		writeFile(t, wt, FileName, `[services.test]
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
		want := "\n\n## Test services\nThis repository declares services for its checks in `megoocolab.toml`: `e2e`, `test` (Postgres for the backend tests). Run every command that needs them as `megoocolab-runner services run <name> -- <command>`. It starts this worktree's own containers on free ports, gives your command the variables the file defines, and removes the containers when the command ends. Do not start, stop or reuse the project's containers any other way, and never touch containers you did not start. If your work adds a check or a command that needs a service, a port or a variable the file does not declare, add it to `megoocolab.toml` (and its Compose files) in the same commit, and run the new check through it. `megoocolab-runner services --help` describes the file.\n"
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
		writeFile(t, wt, FileName, "# nothing yet\n")
		got, err := PromptSection(wt)
		if got != "" || err != nil {
			t.Errorf("= %q, %v", got, err)
		}
	})

	t.Run("invalid file", func(t *testing.T) {
		wt := t.TempDir()
		writeFile(t, wt, FileName, "[services.test]\ncompose = [\"missing.yml\"]\n")
		got, err := PromptSection(wt)
		if got != "" || err == nil {
			t.Errorf("= %q, %v", got, err)
		}
	})

	t.Run("only the worktree's own file", func(t *testing.T) {
		parent := t.TempDir()
		writeFile(t, parent, "svc/compose.yml", "services: {}\n")
		writeFile(t, parent, FileName, "[services.test]\ncompose = [\"svc/compose.yml\"]\n")
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

func TestPlanSection(t *testing.T) {
	const noFile = "This repository has no `megoocolab.toml`. With one, the runner gives each worktree its own copy of the containers a check needs (a database, a search engine, the whole app) on free ports, and removes them when the check ends, so the checks of different tasks never share containers.\n" +
		"Find out how this repository's checks get their services: Compose files, the CI configuration, the README, the test settings. If any check needs a container, make \"Add megoocolab.toml\" the plan's first step, and say in the plan that the runner asked for this step, not the design. That step writes `megoocolab.toml` (and a Compose file for the checks if the repository has none that fits), changes the repository's instructions for running its checks (AGENTS.md, README or the like) to use `megoocolab-runner services run <name> -- <command>`, and proves each set by running its check through it. Later steps run those checks the same way. If no check needs a container, add no step."
	const keep = "A step that adds a check or a command needing a service, a port or a variable the file does not declare changes `megoocolab.toml`, its Compose files and the repository's instructions for running checks in that same step, and runs the new check through `megoocolab-runner services run`."
	section := func(body string) string {
		return "\n\n## Test services\n" + body + "\n\n" + Format
	}

	t.Run("no file", func(t *testing.T) {
		got, err := PlanSection(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}
		if want := section(noFile); got != want {
			t.Errorf("section =\n%q\nwant\n%q", got, want)
		}
	})

	t.Run("sets", func(t *testing.T) {
		wt := t.TempDir()
		writeFile(t, wt, "svc/compose.yml", "services: {}\n")
		writeFile(t, wt, FileName, `[services.test]
description = "Postgres for the backend tests"
compose = ["svc/compose.yml"]
ports = ["DB_PORT"]

[services.e2e]
compose = ["svc/compose.yml"]
`)
		got, err := PlanSection(wt)
		if err != nil {
			t.Fatal(err)
		}
		want := section("This repository declares services for its checks in `megoocolab.toml`: `e2e`, `test` (Postgres for the backend tests). Steps run every command that needs them as `megoocolab-runner services run <name> -- <command>`. " + keep)
		if got != want {
			t.Errorf("section =\n%q\nwant\n%q", got, want)
		}
	})

	t.Run("no sets", func(t *testing.T) {
		wt := t.TempDir()
		writeFile(t, wt, FileName, "# nothing yet\n")
		got, err := PlanSection(wt)
		if err != nil {
			t.Fatal(err)
		}
		if want := section("This repository has a `megoocolab.toml` that declares no services yet. " + keep); got != want {
			t.Errorf("section =\n%q\nwant\n%q", got, want)
		}
		if strings.Contains(got, "Add megoocolab.toml") {
			t.Errorf("section asks to add the file it already has:\n%s", got)
		}
	})

	t.Run("invalid file", func(t *testing.T) {
		wt := t.TempDir()
		writeFile(t, wt, FileName, "[services.test]\ncompose = [\"missing.yml\"]\n")
		got, err := PlanSection(wt)
		if got != "" || err == nil {
			t.Errorf("= %q, %v", got, err)
		}
	})

	t.Run("only in a parent folder", func(t *testing.T) {
		parent := t.TempDir()
		writeFile(t, parent, "svc/compose.yml", "services: {}\n")
		writeFile(t, parent, FileName, "[services.test]\ncompose = [\"svc/compose.yml\"]\n")
		wt := filepath.Join(parent, "wt")
		if err := os.Mkdir(wt, 0o755); err != nil {
			t.Fatal(err)
		}
		got, err := PlanSection(wt)
		if err != nil {
			t.Fatal(err)
		}
		if want := section(noFile); got != want {
			t.Errorf("section =\n%q\nwant\n%q", got, want)
		}
	})
}
