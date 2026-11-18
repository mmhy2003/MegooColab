package services

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

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
