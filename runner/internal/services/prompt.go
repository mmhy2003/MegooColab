package services

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

// Format is megoocolab.toml's format, for agents: a planning run gets it in its
// prompt, and `megoocolab-runner services --help` shows it to writable runs.
const Format = `megoocolab.toml, at the repository's root, declares the containers the checks need. Each [services.<name>] table is a set:
- compose (required): one or more Docker Compose files, relative to megoocolab.toml.
- ports: names of variables. The runner picks a free port on 127.0.0.1 for each.
- env: more variables. A value may use ${NAME} for a port, for MEGOO_SERVICES_PROJECT (the set's unique Compose project name, also usable as an image tag), or for a variable already in the environment.
- description: optional, one line of at most 200 characters, shown to agents.
A set's name is a lowercase letter followed by lowercase letters and digits, with single hyphens between them, 20 characters at most. Variable names are those of environment variables; names starting with MEGOO_SERVICES_ are reserved.
The ports, the env entries and MEGOO_SERVICES_PROJECT go both to Docker Compose (so "127.0.0.1:${DB_PORT}:5432" works in a Compose file) and to the command. A .env file beside the Compose files is never read.
Example:

    [services.test]
    description = "PostgreSQL for the backend tests"
    compose = ["tools/test-services/docker-compose.yml"]
    ports = ["DB_PORT"]

    [services.test.env]
    DATABASE_URL = "postgresql://test:test@localhost:${DB_PORT}/test"

Run a check with its set as: megoocolab-runner services run <name> -- <command>
`

// keepUpToDate ends a writable run's section.
const keepUpToDate = "If your work adds a check or a command that needs a service, a port or a variable the file does not " +
	"declare, add it to `megoocolab.toml` (and its Compose files) in the same commit, and run the new check through it. " +
	"`megoocolab-runner services --help` describes the file."

// planKeep is the planning rule once the file exists.
const planKeep = "A step that adds a check or a command needing a service, a port or a variable the file does not declare " +
	"changes `megoocolab.toml`, its Compose files and the repository's instructions for running checks in that same " +
	"step, and runs the new check through `megoocolab-runner services run`."

// planNoFile is the planning text for a repository without the file.
const planNoFile = "This repository has no `megoocolab.toml`. With one, the runner gives each worktree its own copy of the " +
	"containers a check needs (a database, a search engine, the whole app) on free ports, and removes them when the " +
	"check ends, so the checks of different tasks never share containers.\n" +
	"Find out how this repository's checks get their services: Compose files, the CI configuration, the README, the " +
	"test settings. If any check needs a container, make \"Add megoocolab.toml\" the plan's first step, and say in the " +
	"plan that the runner asked for this step, not the design. That step writes `megoocolab.toml` (and a Compose file " +
	"for the checks if the repository has none that fits), changes the repository's instructions for running its " +
	"checks (AGENTS.md, README or the like) to use `megoocolab-runner services run <name> -- <command>`, and proves " +
	"each set by running its check through it. Later steps run those checks the same way. If no check needs a " +
	"container, add no step."

// PromptSection is the text a writable run's prompt gets about the worktree's
// service sets: "" when the worktree has no megoocolab.toml or it declares no
// set. Only the worktree's own file counts, not one in a parent folder.
func PromptSection(worktree string) (string, error) {
	f, err := loadOwn(worktree)
	if err != nil || f == nil || len(f.Sets) == 0 {
		return "", err
	}
	return "\n\n## Test services\nThis repository declares services for its checks in `megoocolab.toml`: " +
		setList(f) +
		". Run every command that needs them as `megoocolab-runner services run <name> -- <command>`. " +
		"It starts this worktree's own containers on free ports, gives your command the variables the file defines, " +
		"and removes the containers when the command ends. Do not start, stop or reuse the project's containers any " +
		"other way, and never touch containers you did not start. " + keepUpToDate + "\n", nil
}

// PlanSection is the text a planning run's prompt gets about megoocolab.toml:
// how to add it in a worktree without one, how to keep it up to date in one
// with it, then the file's format. Only the worktree's own file counts.
func PlanSection(worktree string) (string, error) {
	f, err := loadOwn(worktree)
	if err != nil {
		return "", err
	}
	var body string
	switch {
	case f == nil:
		body = planNoFile
	case len(f.Sets) == 0:
		body = "This repository has a `megoocolab.toml` that declares no services yet. " + planKeep
	default:
		body = "This repository declares services for its checks in `megoocolab.toml`: " + setList(f) +
			". Steps run every command that needs them as `megoocolab-runner services run <name> -- <command>`. " + planKeep
	}
	return "\n\n## Test services\n" + body + "\n\n" + Format, nil
}

// loadOwn loads the worktree's own megoocolab.toml, not one in a parent
// folder: nil, nil when it has none.
func loadOwn(worktree string) (*File, error) {
	path := filepath.Join(worktree, FileName)
	if _, err := os.Stat(path); errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	return Load(path)
}

// setList names the sets for a prompt: `name` (description), sorted.
func setList(f *File) string {
	sets := make([]string, 0, len(f.Sets))
	for _, name := range f.Names() {
		s := "`" + name + "`"
		if d := f.Sets[name].Description; d != "" {
			s += " (" + d + ")"
		}
		sets = append(sets, s)
	}
	return strings.Join(sets, ", ")
}
