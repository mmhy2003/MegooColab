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

// PromptSection is the text a writable run's prompt gets about the worktree's
// service sets: "" when the worktree has no megoocolab.toml or it declares no
// set. Only the worktree's own file counts, not one in a parent folder.
func PromptSection(worktree string) (string, error) {
	path := filepath.Join(worktree, FileName)
	if _, err := os.Stat(path); errors.Is(err, fs.ErrNotExist) {
		return "", nil
	}
	f, err := Load(path)
	if err != nil {
		return "", err
	}
	if len(f.Sets) == 0 {
		return "", nil
	}
	sets := make([]string, 0, len(f.Sets))
	for _, name := range f.Names() {
		s := "`" + name + "`"
		if d := f.Sets[name].Description; d != "" {
			s += " (" + d + ")"
		}
		sets = append(sets, s)
	}
	return "\n\n## Test services\nThis repository declares services for its checks in `megoocolab.toml`: " +
		strings.Join(sets, ", ") +
		". Run every command that needs them as `megoocolab-runner services run <name> -- <command>`. " +
		"It starts this worktree's own containers on free ports, gives your command the variables the file defines, " +
		"and removes the containers when the command ends. Do not start, stop or reuse the project's containers any " +
		"other way, and never touch containers you did not start.\n", nil
}
