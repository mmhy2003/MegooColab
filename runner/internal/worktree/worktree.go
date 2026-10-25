// Package worktree gives every task its own git worktree so the agent never
// works in the developer's checkout.
package worktree

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"

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

func git(repo string, args ...string) (string, error) {
	out, err := exec.Command("git", append(append([]string{"-C", repo}, gitstate.HardenedArgs()...), args...)...).CombinedOutput()
	s := strings.TrimSpace(string(out))
	if err != nil {
		return s, fmt.Errorf("git %s: %w: %s", args[0], err, s)
	}
	return s, nil
}

// Ensure returns the worktree for a task, creating it (and its branch) from
// HEAD of repo if needed, and reusing it if it is already registered.
func Ensure(repo, cacheRoot, agentID, taskKey, title string) (path, branch string, err error) {
	if out, e := git(repo, "rev-parse", "--is-inside-work-tree"); e != nil || out != "true" {
		return "", "", fmt.Errorf("worktree: %q is not a git work tree", repo)
	}
	if !safeID.MatchString(taskKey) || !safeID.MatchString(agentID) {
		return "", "", fmt.Errorf("worktree: unsafe agent id or task key")
	}
	branch = "megoo/" + taskKey + "-" + Slug(title)
	path = filepath.Join(cacheRoot, "worktrees", agentID, taskKey)
	if rel, e := filepath.Rel(filepath.Join(cacheRoot, "worktrees"), path); e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", "", fmt.Errorf("worktree: path escapes the worktree root")
	}

	if _, statErr := os.Stat(path); statErr == nil {
		registered, e := isRegistered(repo, path)
		if e != nil {
			return "", "", e
		}
		if !registered {
			return "", "", fmt.Errorf("worktree: %s exists but is not a worktree of %s; remove it manually", path, repo)
		}
		return path, branch, nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return "", "", err
	}
	args := []string{"worktree", "add", "-b", branch, path}
	if _, e := git(repo, "show-ref", "--verify", "--quiet", "refs/heads/"+branch); e == nil {
		args = []string{"worktree", "add", path, branch}
	}
	if _, e := git(repo, args...); e != nil {
		return "", "", e
	}
	return path, branch, nil
}

func isRegistered(repo, path string) (bool, error) {
	out, err := git(repo, "worktree", "list", "--porcelain")
	if err != nil {
		return false, err
	}
	want := canon(path)
	for _, line := range strings.Split(out, "\n") {
		if p, ok := strings.CutPrefix(strings.TrimSpace(line), "worktree "); ok && canon(p) == want {
			return true, nil
		}
	}
	return false, nil
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
