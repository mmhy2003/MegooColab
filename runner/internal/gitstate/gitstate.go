// Package gitstate reads a worktree's git state for run_start/run_finished and
// writes MegooColab's files into it: the read-only .megoocolab/ context files
// and the design/plan documents that are committed before the agent starts.
//
// Every path the server sends is validated here again with the same rules as
// backend/app/runner/protocol.py (check_relative_path), so a compromised server
// cannot make the runner write outside the two allowed directories.
package gitstate

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

const (
	// FilesPrefix is where MegooColab's read-only context files live.
	FilesPrefix = ".megoocolab/"
	// RepoFilesPrefix is where committed design and plan documents live.
	RepoFilesPrefix = "docs/superpowers/"
	// MaxFilesBytes bounds the total content of one file set.
	MaxFilesBytes = 2 * 1024 * 1024
	// MaxBranchRunes is the longest branch name sent to the server.
	MaxBranchRunes = 200

	excludeLine = "/.megoocolab/"
)

var (
	component = regexp.MustCompile(`^[A-Za-z0-9._-]+$`)
	headRe    = regexp.MustCompile(`^(?:[0-9a-f]{40}|[0-9a-f]{64})$`)
	reserved  = map[string]bool{"CON": true, "PRN": true, "AUX": true, "NUL": true}
)

func init() {
	for i := 1; i <= 9; i++ {
		reserved[fmt.Sprintf("COM%d", i)] = true
		reserved[fmt.Sprintf("LPT%d", i)] = true
	}
}

func safeComponent(c string) bool {
	if c == "." || c == ".." || strings.HasSuffix(c, ".") {
		return false
	}
	return !reserved[strings.ToUpper(strings.SplitN(c, ".", 2)[0])]
}

// CheckPath reports whether p is a normalised relative path strictly below
// prefix whose components are all safe on every platform.
func CheckPath(p, prefix string) error {
	if strings.ContainsAny(p, "\\\x00:") || strings.HasPrefix(p, "/") || !strings.HasPrefix(p, prefix) ||
		len(p) == len(prefix) || path.Clean(p) != p {
		return fmt.Errorf("path not allowed: %q", p)
	}
	for _, c := range strings.Split(p, "/") {
		if !component.MatchString(c) || !safeComponent(c) {
			return fmt.Errorf("path not allowed: %q", p)
		}
	}
	return nil
}

func checkFiles(files []protocol.File, prefix string) error {
	total := 0
	for _, f := range files {
		if err := CheckPath(f.Path, prefix); err != nil {
			return err
		}
		total += len(f.Content)
	}
	if total > MaxFilesBytes {
		return fmt.Errorf("files exceed %d bytes", MaxFilesBytes)
	}
	return nil
}

// git runs git in dir. quotepath is off so paths come back as they are.
func git(dir string, args ...string) (string, error) {
	full := append([]string{"-C", dir, "-c", "core.quotepath=off"}, args...)
	cmd := exec.Command("git", full...)
	cmd.Env = append(os.Environ(), "GIT_OPTIONAL_LOCKS=0", "GIT_TERMINAL_PROMPT=0")
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		return out.String(), fmt.Errorf("git %s: %w: %s", args[0], err, strings.TrimSpace(errb.String()))
	}
	return out.String(), nil
}

// Read returns the worktree's HEAD, branch and whether it has changes outside
// .megoocolab/. Head is nil when the repository has no commits. An error means
// the state is unknown; callers must not send a guess.
func Read(dir string) (protocol.GitState, error) {
	var st protocol.GitState
	if _, err := git(dir, "rev-parse", "--git-dir"); err != nil {
		return st, err
	}
	if out, err := git(dir, "rev-parse", "--verify", "-q", "HEAD"); err == nil {
		h := strings.TrimSpace(out)
		if !headRe.MatchString(h) {
			return st, fmt.Errorf("unexpected HEAD %q", h)
		}
		st.Head = &h
		br, err := git(dir, "rev-parse", "--abbrev-ref", "HEAD")
		if err != nil {
			return st, err
		}
		b := truncateRunes(strings.TrimSpace(br), MaxBranchRunes)
		st.Branch = &b
	} else if br, err := git(dir, "symbolic-ref", "--short", "-q", "HEAD"); err == nil && strings.TrimSpace(br) != "" {
		b := truncateRunes(strings.TrimSpace(br), MaxBranchRunes) // unborn branch
		st.Branch = &b
	}
	out, err := git(dir, "status", "--porcelain", "-z", "--untracked-files=all")
	if err != nil {
		return st, err
	}
	st.Dirty = dirty(out)
	return st, nil
}

func truncateRunes(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}

// dirty parses `status --porcelain -z`: "XY path" entries, where a rename or
// copy is followed by one more entry holding the original path.
func dirty(out string) bool {
	entries := strings.Split(out, "\x00")
	for i := 0; i < len(entries); i++ {
		e := entries[i]
		if len(e) < 4 {
			continue
		}
		paths := []string{e[3:]}
		if e[0] == 'R' || e[0] == 'C' || e[1] == 'R' || e[1] == 'C' {
			if i+1 < len(entries) {
				paths = append(paths, entries[i+1])
			}
			i++
		}
		for _, p := range paths {
			if p != strings.TrimSuffix(FilesPrefix, "/") && !strings.HasPrefix(p, FilesPrefix) {
				return true
			}
		}
	}
	return false
}

// resolve joins a validated relative path onto root, refusing to pass through
// a symlink (an agent could have replaced a directory with a link).
func resolve(root, rel string, create bool) (string, error) {
	cur := root
	parts := strings.Split(rel, "/")
	for i, c := range parts {
		cur = filepath.Join(cur, c)
		fi, err := os.Lstat(cur)
		switch {
		case err == nil:
			if fi.Mode()&os.ModeSymlink != 0 {
				return "", fmt.Errorf("%q is a symlink", rel)
			}
			if i < len(parts)-1 && !fi.IsDir() {
				return "", fmt.Errorf("%q: parent is not a directory", rel)
			}
			if i == len(parts)-1 && fi.IsDir() {
				return "", fmt.Errorf("%q is a directory", rel)
			}
		case errors.Is(err, os.ErrNotExist):
			if create && i < len(parts)-1 {
				if err := os.Mkdir(cur, 0o755); err != nil {
					return "", err
				}
			}
		default:
			return "", err
		}
	}
	return cur, nil
}

// writeFile replaces any previous (possibly read-only) copy of the file.
func writeFile(root string, f protocol.File, mode os.FileMode) error {
	p, err := resolve(root, f.Path, true)
	if err != nil {
		return err
	}
	if _, err := os.Lstat(p); err == nil {
		if err := os.Chmod(p, 0o644); err != nil {
			return err
		}
	}
	if err := os.WriteFile(p, []byte(f.Content), 0o644); err != nil {
		return err
	}
	return os.Chmod(p, mode)
}

// Materialize makes .megoocolab/ in the worktree hold exactly files, read-only,
// and keeps it out of git status via the repository's info/exclude.
func Materialize(worktree string, files []protocol.File) error {
	if err := checkFiles(files, FilesPrefix); err != nil {
		return err
	}
	if err := ensureExcluded(worktree); err != nil {
		return err
	}
	keep := map[string]bool{}
	for _, f := range files {
		keep[f.Path] = true
	}
	if err := pruneStale(worktree, keep); err != nil {
		return err
	}
	for _, f := range files {
		if err := writeFile(worktree, f, 0o444); err != nil {
			return err
		}
	}
	return nil
}

// pruneStale removes files under .megoocolab/ that are not in keep, then any
// directories left empty.
func pruneStale(worktree string, keep map[string]bool) error {
	root := filepath.Join(worktree, strings.TrimSuffix(FilesPrefix, "/"))
	fi, err := os.Lstat(root)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if fi.Mode()&os.ModeSymlink != 0 || !fi.IsDir() {
		return fmt.Errorf("%s is not a directory", FilesPrefix)
	}
	var dirs []string
	err = filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(worktree, p)
		rel = filepath.ToSlash(rel)
		if d.IsDir() {
			if p != root {
				dirs = append(dirs, p)
			}
			return nil
		}
		if keep[rel] && d.Type().IsRegular() {
			return nil
		}
		_ = os.Chmod(p, 0o644) // Windows cannot delete a read-only file
		return os.Remove(p)
	})
	if err != nil {
		return err
	}
	for i := len(dirs) - 1; i >= 0; i-- {
		_ = os.Remove(dirs[i]) // fails (and stays) when not empty
	}
	return nil
}

// ensureExcluded adds /.megoocolab/ to <git-common-dir>/info/exclude once.
func ensureExcluded(worktree string) error {
	out, err := git(worktree, "rev-parse", "--git-common-dir")
	if err != nil {
		return err
	}
	dir := strings.TrimSpace(out)
	if !filepath.IsAbs(dir) {
		dir = filepath.Join(worktree, dir)
	}
	if err := os.MkdirAll(filepath.Join(dir, "info"), 0o755); err != nil {
		return err
	}
	p := filepath.Join(dir, "info", "exclude")
	cur, err := os.ReadFile(p)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	for _, l := range strings.Split(string(cur), "\n") {
		if strings.TrimSpace(l) == excludeLine {
			return nil
		}
	}
	add := excludeLine + "\n"
	if len(cur) > 0 && !bytes.HasSuffix(cur, []byte("\n")) {
		add = "\n" + add
	}
	f, err := os.OpenFile(p, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	_, werr := f.WriteString(add)
	if cerr := f.Close(); werr == nil {
		werr = cerr
	}
	return werr
}

// CommitRepoFiles writes files (design and plan documents) into the worktree
// and commits them. It does nothing when they are already committed unchanged.
func CommitRepoFiles(worktree string, files []protocol.File, message string) error {
	if err := checkFiles(files, RepoFilesPrefix); err != nil {
		return err
	}
	if len(files) == 0 {
		return nil
	}
	if strings.TrimSpace(message) == "" {
		return errors.New("empty commit message")
	}
	paths := make([]string, 0, len(files))
	for _, f := range files {
		if err := writeFile(worktree, f, 0o644); err != nil {
			return err
		}
		paths = append(paths, f.Path)
	}
	if _, err := git(worktree, append([]string{"--literal-pathspecs", "add", "--"}, paths...)...); err != nil {
		return err
	}
	if _, err := git(worktree, append([]string{"--literal-pathspecs", "diff", "--cached", "--quiet", "--"}, paths...)...); err == nil {
		return nil // nothing changed
	}
	// --no-verify: repo hooks must not run as part of MegooColab's own commit
	// (they are the project's checks on the agent's work, not on our documents).
	args := []string{"--literal-pathspecs"}
	if out, _ := git(worktree, "config", "user.email"); strings.TrimSpace(out) == "" {
		args = append(args, "-c", "user.name=MegooColab", "-c", "user.email=megoocolab@localhost")
	}
	args = append(args, "-c", "commit.gpgsign=false", "commit", "--no-verify", "-m", message, "--")
	args = append(args, paths...)
	_, err := git(worktree, args...)
	return err
}
