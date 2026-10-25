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
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

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

var (
	gitBin  = "git"
	timeout = 30 * time.Second // per git call; a var so tests can shorten it

	hooksMu  sync.Mutex
	hooksDir string
)

// SetHooksDir sets the empty directory every runner git call uses as
// core.hooksPath (e.g. <cacheRoot>/empty-hooks); it is created on demand.
func SetHooksDir(dir string) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return
	}
	hooksMu.Lock()
	hooksDir = dir
	hooksMu.Unlock()
}

func emptyHooksDir() string {
	hooksMu.Lock()
	defer hooksMu.Unlock()
	if hooksDir == "" || !isDir(hooksDir) {
		if d, err := os.MkdirTemp("", "megoocolab-empty-hooks-"); err == nil {
			hooksDir = d
		}
	}
	return hooksDir
}

func isDir(p string) bool { fi, err := os.Stat(p); return err == nil && fi.IsDir() }

// HardenedArgs are the git options every runner git call starts with. A
// worktree's config is writable by the agent, and these keep it from making
// git run code (hooks, fsmonitor) or from changing what we read.
func HardenedArgs() []string {
	return []string{
		"-c", "core.quotepath=off",
		"-c", "core.hooksPath=" + emptyHooksDir(),
		"-c", "core.fsmonitor=false",
		"-c", "core.untrackedCache=false",
	}
}

// git runs git in dir with a timeout.
func git(dir string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	full := append(append([]string{"-C", dir}, HardenedArgs()...), args...)
	cmd := exec.CommandContext(ctx, gitBin, full...)
	cmd.Env = append(os.Environ(), "GIT_OPTIONAL_LOCKS=0", "GIT_TERMINAL_PROMPT=0")
	cmd.WaitDelay = time.Second // a grandchild holding a pipe cannot block forever
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		if ctx.Err() != nil {
			return out.String(), fmt.Errorf("git %s: timed out after %v", args[0], timeout)
		}
		return out.String(), fmt.Errorf("git %s: %w: %s", args[0], err, strings.TrimSpace(errb.String()))
	}
	return out.String(), nil
}

// Read returns the worktree's HEAD, branch and whether it has changes outside
// .megoocolab/. Head is nil when the repository has no commits. An error means
// the state is unknown; callers must not send a guess. Capture adds the checks
// that need a baseline.
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

// flaggedSet lists the tracked files tagged S (skip-worktree) or with a
// lowercase tag (assume-unchanged) in `ls-files -v -z` output, tag included,
// sorted. Those flags hide edits from status, so a run that changes the set is
// dirty; flags that were already there (a sparse checkout) are not.
func flaggedSet(out string) string {
	var set []string
	for _, e := range strings.Split(out, "\x00") {
		if len(e) >= 2 && (e[0] == 'S' || (e[0] >= 'a' && e[0] <= 'z')) {
			set = append(set, e)
		}
	}
	sort.Strings(set)
	return strings.Join(set, "\x00")
}

// Snapshot is a Read plus what Read alone cannot tell: the untracked-but-ignored
// files and the stash, which a run can use to hide its changes from status.
type Snapshot struct {
	State   protocol.GitState
	ignored string
	flagged string
	stash   string
}

// Capture reads a Snapshot.
func Capture(dir string) (Snapshot, error) {
	st, err := Read(dir)
	if err != nil {
		return Snapshot{}, err
	}
	out, err := git(dir, "ls-files", "-o", "-i", "--exclude-standard", "--directory", "-z")
	if err != nil {
		return Snapshot{}, err
	}
	var ign []string
	for _, p := range strings.Split(out, "\x00") {
		if p != "" && !strings.HasPrefix(p, FilesPrefix) {
			ign = append(ign, p)
		}
	}
	sort.Strings(ign)
	lv, err := git(dir, "ls-files", "-v", "-z")
	if err != nil {
		return Snapshot{}, err
	}
	stash, _ := git(dir, "rev-parse", "--verify", "-q", "refs/stash") // absent: empty
	return Snapshot{State: st, ignored: strings.Join(ign, "\x00"), flagged: flaggedSet(lv), stash: strings.TrimSpace(stash)}, nil
}

// After is the state to report once a run ended: after's own state, dirty also
// when the run changed the set of ignored files, of skip-worktree or
// assume-unchanged files, or the stash since before. With
// no baseline only after's own state is known.
func After(before *Snapshot, after Snapshot) protocol.GitState {
	st := after.State
	if before != nil && (before.ignored != after.ignored || before.flagged != after.flagged || before.stash != after.stash) {
		st.Dirty = true
	}
	return st
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
			if !strings.HasPrefix(p, FilesPrefix) {
				return true
			}
		}
	}
	return false
}

// resolve joins a validated relative path onto root, refusing to pass through
// isLink reports a symlink or a Windows junction/mount point.
func isLink(fi os.FileInfo) bool { return fi.Mode()&(os.ModeSymlink|os.ModeIrregular) != 0 }

// resolve joins a validated relative path onto root, refusing to pass through
// a symlink or junction (an agent could have replaced a directory with a link).
func resolve(root, rel string, create bool) (string, error) {
	cur := root
	parts := strings.Split(rel, "/")
	for i, c := range parts {
		cur = filepath.Join(cur, c)
		fi, err := os.Lstat(cur)
		switch {
		case err == nil:
			if isLink(fi) {
				return "", fmt.Errorf("%q is a link", rel)
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

// removeEntry deletes a file, link or empty directory itself, never what a
// link points to. Only a regular file is made writable first (chmod would
// follow a link).
func removeEntry(p string, fi os.FileInfo) error {
	if fi.Mode().IsRegular() {
		_ = os.Chmod(p, 0o644) // Windows cannot delete a read-only file
	}
	return os.Remove(p)
}

// Materialize makes .megoocolab/ in the worktree hold exactly files, read-only,
// and keeps it out of git status via the repository info/exclude. With no
// files it only removes what an earlier run left behind.
func Materialize(worktree string, files []protocol.File) error {
	if err := checkFiles(files, FilesPrefix); err != nil {
		return err
	}
	if len(files) > 0 {
		if err := ensureExcluded(worktree); err != nil {
			return err
		}
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
// directories left empty. A .megoocolab that is not a real directory (a file,
// a link) is removed itself, never followed.
func pruneStale(worktree string, keep map[string]bool) error {
	root := filepath.Join(worktree, strings.TrimSuffix(FilesPrefix, "/"))
	fi, err := os.Lstat(root)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if isLink(fi) || !fi.IsDir() {
		return removeEntry(root, fi)
	}
	var dirs []string
	err = filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(worktree, p)
		rel = filepath.ToSlash(rel)
		fi, err := d.Info()
		if err != nil {
			return err
		}
		if fi.IsDir() && !isLink(fi) {
			if p != root {
				dirs = append(dirs, p)
			}
			return nil
		}
		if keep[rel] && fi.Mode().IsRegular() {
			return nil
		}
		return removeEntry(p, fi)
	})
	if err != nil {
		return err
	}
	for i := len(dirs) - 1; i >= 0; i-- {
		_ = os.Remove(dirs[i]) // fails (and stays) when not empty
	}
	return nil
}

func sameFile(a, b string) bool {
	fa, err := os.Stat(a)
	if err != nil {
		return false
	}
	fb, err := os.Stat(b)
	return err == nil && os.SameFile(fa, fb)
}

// gitCommonDir returns the repository common git dir after checking that it
// really belongs to this worktree: either <worktree>/.git itself, or a linked
// worktree whose admin dir points back at <worktree>/.git. An agent can edit
// the .git file, and the exclude file must not be written into another repo.
func gitCommonDir(worktree string) (string, error) {
	abs := func(args ...string) (string, error) {
		out, err := git(worktree, args...)
		if err != nil {
			return "", err
		}
		d := strings.TrimSpace(out)
		if !filepath.IsAbs(d) {
			d = filepath.Join(worktree, d)
		}
		return filepath.Clean(d), nil
	}
	gitdir, err := abs("rev-parse", "--git-dir")
	if err != nil {
		return "", err
	}
	common, err := abs("rev-parse", "--git-common-dir")
	if err != nil {
		return "", err
	}
	dotgit := filepath.Join(worktree, ".git")
	if sameFile(gitdir, common) {
		if !sameFile(common, dotgit) {
			return "", errors.New("git dir does not belong to this worktree")
		}
		return common, nil
	}
	back, err := os.ReadFile(filepath.Join(gitdir, "gitdir"))
	if err != nil || !sameFile(strings.TrimSpace(string(back)), dotgit) ||
		filepath.Base(filepath.Dir(gitdir)) != "worktrees" || !sameFile(filepath.Dir(filepath.Dir(gitdir)), common) {
		return "", errors.New("git dir does not belong to this worktree")
	}
	return common, nil
}

// ensureExcluded adds /.megoocolab/ to <git-common-dir>/info/exclude once.
func ensureExcluded(worktree string) error {
	dir, err := gitCommonDir(worktree)
	if err != nil {
		return err
	}
	info := filepath.Join(dir, "info")
	p := filepath.Join(info, "exclude")
	if fi, err := os.Lstat(info); err == nil {
		if isLink(fi) || !fi.IsDir() {
			return errors.New("info is not a plain directory")
		}
	} else if errors.Is(err, os.ErrNotExist) {
		if err := os.Mkdir(info, 0o755); err != nil {
			return err
		}
	} else {
		return err
	}
	if fi, err := os.Lstat(p); err == nil {
		if isLink(fi) || !fi.Mode().IsRegular() {
			return errors.New("info/exclude is not a plain file")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
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
	// -f: the paths are validated and ours; a .gitignore must not stop them.
	if _, err := git(worktree, append([]string{"--literal-pathspecs", "add", "-f", "--"}, paths...)...); err != nil {
		return err
	}
	if _, err := git(worktree, append([]string{"--literal-pathspecs", "diff", "--cached", "--quiet", "--"}, paths...)...); err == nil {
		return nil // nothing changed
	}
	// --no-verify skips pre-commit and commit-msg; every runner git call also
	// runs with core.hooksPath pointing at an empty directory (HardenedArgs), so
	// no repo hook (prepare-commit-msg, post-commit, ...) runs as part of our
	// own commit.
	args := []string{"--literal-pathspecs"}
	if out, _ := git(worktree, "config", "user.email"); strings.TrimSpace(out) == "" {
		args = append(args, "-c", "user.name=MegooColab", "-c", "user.email=megoocolab@localhost")
	}
	args = append(args, "-c", "commit.gpgsign=false", "commit", "--no-verify", "-m", message, "--")
	args = append(args, paths...)
	_, err := git(worktree, args...)
	return err
}
