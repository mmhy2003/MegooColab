// Package worktree gives every task its own git worktree so the agent never
// works in the developer's checkout.
package worktree

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/gitstate"
)

var safeID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

// Slug turns a task title into a branch-name fragment: lowercase, runs of
// non-alphanumerics become one "-", at most 40 characters, "task" if empty.
func Slug(title string) string {
	var b strings.Builder
	dash := false
	for _, r := range strings.ToLower(title) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			if dash && b.Len() > 0 {
				b.WriteByte('-')
			}
			dash = false
			b.WriteRune(r)
		} else {
			dash = true
		}
	}
	s := b.String()
	if len(s) > 40 {
		s = s[:40]
	}
	s = strings.TrimRight(s, "-")
	if s == "" {
		return "task"
	}
	return s
}

// addTimeout bounds `git worktree add`, which checks out the whole tree and can
// legitimately take minutes (a large repository, antivirus scanning each new
// file). Every other git call keeps gitstate's default. A var for tests.
var addTimeout = 10 * time.Minute

// initializingLock is the lock reason `git worktree add` puts on a worktree
// before it checks out any file, and removes once the checkout is done.
// gitstate runs git with LC_ALL=C, so our adds write it in English.
const initializingLock = "initializing"

func git(repo string, args ...string) (string, error) {
	out, err := gitstate.Run(repo, args...)
	return strings.TrimSpace(out), err
}

// Ensure returns the worktree for a task, creating it (and its branch) from
// HEAD of repo if needed, and reusing it if it is already registered and
// healthy. ctx is the run's: cancelling it aborts a worktree add in progress.
// A failed add is cleaned up before Ensure returns, so a retry starts afresh.
// What Ensure repairs, and cleanup that fails, is written to logw.
func Ensure(ctx context.Context, logw io.Writer, repo, cacheRoot, agentID, taskKey, title string) (path, branch string, err error) {
	path, branch, _, err = EnsureFrom(ctx, logw, repo, cacheRoot, agentID, taskKey, title, nil)
	return path, branch, err
}

// EnsureFrom is Ensure with the start point of a new branch: startPoint is
// called only when the task's branch has to be created ("" is HEAD), and its
// error is returned as is. created says the branch was created by this call.
func EnsureFrom(ctx context.Context, logw io.Writer, repo, cacheRoot, agentID, taskKey, title string,
	startPoint func() (string, error)) (path, branch string, created bool, err error) {
	if logw == nil {
		logw = io.Discard
	}
	if out, e := git(repo, "rev-parse", "--is-inside-work-tree"); e != nil || out != "true" {
		return "", "", false, fmt.Errorf("worktree: %q is not a git work tree", repo)
	}
	if !safeID.MatchString(taskKey) || !safeID.MatchString(agentID) {
		return "", "", false, fmt.Errorf("worktree: unsafe agent id or task key")
	}
	branch = "megoo/" + taskKey + "-" + Slug(title)
	path = filepath.Join(cacheRoot, "worktrees", agentID, taskKey)
	if rel, e := filepath.Rel(filepath.Join(cacheRoot, "worktrees"), path); e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", "", false, fmt.Errorf("worktree: path escapes the worktree root")
	}
	unlock, err := lockPath(ctx, path)
	if err != nil {
		return "", "", false, fmt.Errorf("worktree: %w", err)
	}
	defer unlock()

	if _, statErr := os.Stat(path); statErr == nil {
		registered, lock, e := worktreeEntry(repo, path)
		if e != nil {
			return "", "", false, e
		}
		if !registered {
			return "", "", false, fmt.Errorf("worktree: %s exists but is not a worktree of %s; remove it manually", path, repo)
		}
		why, e := broken(path, lock)
		if e != nil {
			return "", "", false, e
		}
		if why == "" {
			return path, branch, false, nil
		}
		fmt.Fprintf(logw, "worktree: %s is broken (%s); recreating it\n", path, why)
		discard(repo, path, logw)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return "", "", false, err
	}
	args := []string{"worktree", "add", "-b", branch, path}
	if _, e := git(repo, "show-ref", "--verify", "--quiet", "refs/heads/"+branch); e == nil {
		args = []string{"worktree", "add", path, branch}
	} else if startPoint != nil {
		point, e := startPoint()
		if e != nil {
			return "", "", false, e
		}
		if point != "" {
			args = append(args, point)
		}
		created = true
	} else {
		created = true
	}
	if _, e := gitstate.RunContext(ctx, addTimeout, repo, args...); e != nil {
		// git registers the worktree, locked as initializing, before it checks
		// out a file: an add that failed part-way leaves a half-written tree
		// that a retry must not be handed.
		discard(repo, path, logw)
		return "", "", false, fmt.Errorf("worktree: %w", e)
	}
	return path, branch, created, nil
}

// broken says why a registered worktree must not be handed to an agent, or ""
// if it is healthy. The signals are git's own:
//   - the "initializing" lock that `worktree add` holds until its checkout is
//     complete. Any other lock reason is someone's deliberate lock and is left
//     alone.
//   - the worktree's HEAD file in its admin directory
//     (<git-common-dir>/worktrees/<name>/HEAD, found through the worktree's
//     .git file), without which git does not see a repository there. A missing
//     .git file, or one that names no admin directory, counts as no HEAD.
func broken(path, lock string) (string, error) {
	if lock == initializingLock {
		return "left locked as initializing by an interrupted git worktree add", nil
	}
	b, err := os.ReadFile(filepath.Join(path, ".git"))
	if errors.Is(err, os.ErrNotExist) {
		return "no .git file", nil
	} else if err != nil {
		return "", fmt.Errorf("worktree: %w", err)
	}
	admin, ok := strings.CutPrefix(strings.TrimSpace(string(b)), "gitdir:")
	if !ok {
		return "no gitdir in .git", nil
	}
	if admin = strings.TrimSpace(admin); !filepath.IsAbs(admin) {
		admin = filepath.Join(path, admin)
	}
	if _, err := os.Stat(filepath.Join(admin, "HEAD")); errors.Is(err, os.ErrNotExist) {
		return "no HEAD", nil
	} else if err != nil {
		return "", fmt.Errorf("worktree: %w", err)
	}
	return "", nil
}

// discard removes the worktree at path, best effort: git's removal first, then
// whatever directory is left, then the registration. Failures are logged; the
// next Ensure finds any remains and tries again.
func discard(repo, path string, logw io.Writer) {
	// --force twice: a single one refuses a locked worktree, and an
	// interrupted add leaves its "initializing" lock.
	if _, err := git(repo, "worktree", "remove", "--force", "--force", path); err != nil {
		fmt.Fprintf(logw, "worktree: cleanup: %v\n", err)
	}
	if _, err := os.Lstat(path); err == nil {
		if err := os.RemoveAll(path); err != nil {
			fmt.Fprintf(logw, "worktree: cleanup: %v\n", err)
		}
	}
	// prune drops a registration whose directory is gone, but not a locked
	// one, so the initializing lock of an add that died is lifted first.
	if registered, lock, err := worktreeEntry(repo, path); err != nil {
		fmt.Fprintf(logw, "worktree: cleanup: %v\n", err)
	} else if registered && lock == initializingLock {
		if _, err := git(repo, "worktree", "unlock", path); err != nil {
			fmt.Fprintf(logw, "worktree: cleanup: %v\n", err)
		}
	}
	if _, err := git(repo, "worktree", "prune"); err != nil {
		fmt.Fprintf(logw, "worktree: cleanup: %v\n", err)
	}
}

var (
	pathsMu sync.Mutex
	busy    = map[string]chan struct{}{} // worktree paths an Ensure is working on
)

// lockPath serializes Ensure calls for one worktree path within the runner. A
// retried run must not find the worktree another run is still adding, take it
// for broken and remove it, nor clean up after its own add failing on it.
func lockPath(ctx context.Context, path string) (unlock func(), err error) {
	key := filepath.Clean(path)
	if runtime.GOOS == "windows" {
		key = strings.ToLower(key)
	}
	for {
		pathsMu.Lock()
		held, ok := busy[key]
		if !ok {
			mine := make(chan struct{})
			busy[key] = mine
			pathsMu.Unlock()
			return func() {
				pathsMu.Lock()
				delete(busy, key)
				pathsMu.Unlock()
				close(mine)
			}, nil
		}
		pathsMu.Unlock()
		select {
		case <-held:
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
}

// worktreeEntry reports whether path is a registered worktree of repo and, if
// it is locked, the lock reason, from `git worktree list --porcelain`.
func worktreeEntry(repo, path string) (registered bool, lock string, err error) {
	out, err := git(repo, "worktree", "list", "--porcelain")
	if err != nil {
		return false, "", err
	}
	want := canon(path)
	for _, block := range strings.Split(strings.ReplaceAll(out, "\r\n", "\n"), "\n\n") {
		lines := strings.Split(strings.TrimSpace(block), "\n")
		p, ok := strings.CutPrefix(lines[0], "worktree ")
		if !ok || canon(p) != want {
			continue
		}
		for _, l := range lines[1:] {
			if reason, ok := strings.CutPrefix(strings.TrimSpace(l), "locked "); ok {
				return true, reason, nil
			}
		}
		return true, "", nil
	}
	return false, "", nil
}

func canon(p string) string {
	if r, err := filepath.EvalSymlinks(p); err == nil {
		p = r
	}
	p = filepath.Clean(p)
	if runtime.GOOS == "windows" {
		p = strings.ToLower(p)
	}
	return p
}
