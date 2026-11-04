// Package drafts keeps a folder for each Knowledge Base draft an agent writes: a detached worktree of the project's
// repository for a project's draft (the agent may read the code, and no branch is made), an empty folder otherwise.
// The folder lasts for the whole draft, so the agent's session resumes across turns; the server's draft_done removes
// it, and Sweep removes the ones whose draft_done never came.
package drafts

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/gitstate"
)

// SweepAge is how long a draft's folder is kept after its last run.
const SweepAge = 30 * 24 * time.Hour

// addTimeout bounds `git worktree add`, which checks out the whole tree.
const addTimeout = 10 * time.Minute

var safeID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

// meta sits beside the folder (never inside, where the agent would see it): the repository a worktree belongs to.
// Its modification time is the draft's last run.
type meta struct {
	Repo string `json:"repo"`
}

func root(cacheRoot string) string { return filepath.Join(cacheRoot, "drafts") }

func folder(cacheRoot, agentID, draftID string) string {
	return filepath.Join(root(cacheRoot), agentID, draftID)
}

func metaPath(cacheRoot, agentID, draftID string) string {
	return folder(cacheRoot, agentID, draftID) + ".meta"
}

func check(agentID, draftID string) error {
	if !safeID.MatchString(agentID) || !safeID.MatchString(draftID) {
		return errors.New("drafts: unsafe agent or draft id")
	}
	return nil
}

// Ensure returns the draft's folder, making it on the first run: a detached worktree of repo at its HEAD, or an
// empty folder when repo is "". Every call marks the draft as used now.
func Ensure(ctx context.Context, cacheRoot, agentID, draftID, repo string) (string, error) {
	if err := check(agentID, draftID); err != nil {
		return "", err
	}
	dir := folder(cacheRoot, agentID, draftID)
	unlock, err := lockPath(ctx, dir)
	if err != nil {
		return "", err
	}
	defer unlock()
	if err := os.MkdirAll(filepath.Dir(dir), 0o755); err != nil {
		return "", err
	}
	b, _ := json.Marshal(meta{Repo: repo})
	if err := os.WriteFile(metaPath(cacheRoot, agentID, draftID), b, 0o600); err != nil {
		return "", err
	}
	if repo == "" {
		return dir, os.MkdirAll(dir, 0o755)
	}
	if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
		return dir, nil
	}
	// a folder left half-made by an interrupted add (or anything else there) is replaced
	removeWorktree(repo, dir)
	if _, err := gitstate.RunContext(ctx, addTimeout, repo, "worktree", "add", "--detach", dir, "HEAD"); err != nil {
		removeWorktree(repo, dir)
		return "", fmt.Errorf("drafts: %w", err)
	}
	return dir, nil
}

// Remove deletes the draft's folder and its worktree registration. Removing a draft that has none is not an error.
func Remove(cacheRoot, agentID, draftID string) error {
	if err := check(agentID, draftID); err != nil {
		return err
	}
	dir := folder(cacheRoot, agentID, draftID)
	unlock, err := lockPath(context.Background(), dir)
	if err != nil {
		return err
	}
	defer unlock()
	var m meta
	if b, err := os.ReadFile(metaPath(cacheRoot, agentID, draftID)); err == nil {
		_ = json.Unmarshal(b, &m)
	}
	if m.Repo != "" {
		removeWorktree(m.Repo, dir)
	}
	if err := os.RemoveAll(dir); err != nil {
		return err
	}
	if err := os.Remove(metaPath(cacheRoot, agentID, draftID)); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

// removeWorktree drops the worktree at dir from repo, best effort: git's removal, then what is left, then the
// registration.
func removeWorktree(repo, dir string) {
	_, _ = gitstate.Run(repo, "worktree", "remove", "--force", "--force", dir)
	_ = os.RemoveAll(dir)
	_, _ = gitstate.Run(repo, "worktree", "prune")
}

// Sweep removes the folders of drafts not used for maxAge: their draft_done was missed (the runner was away when the
// draft was saved or discarded). It returns what it could not remove.
func Sweep(cacheRoot string, maxAge time.Duration, now time.Time) []error {
	var errs []error
	agents, err := os.ReadDir(root(cacheRoot))
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return []error{err}
	}
	for _, a := range agents {
		if !a.IsDir() {
			continue
		}
		entries, err := os.ReadDir(filepath.Join(root(cacheRoot), a.Name()))
		if err != nil {
			errs = append(errs, err)
			continue
		}
		for _, e := range entries {
			draftID := e.Name()
			last := filepath.Join(root(cacheRoot), a.Name(), draftID)
			if !e.IsDir() {
				if draftID, ok := strings.CutSuffix(e.Name(), ".meta"); !ok || dirExists(folder(cacheRoot, a.Name(), draftID)) {
					continue // a meta beside its folder is judged with the folder
				}
			} else if dirExists(last + ".meta") {
				last += ".meta" // the meta's time is the draft's last run
			}
			info, err := os.Stat(last)
			if err != nil || now.Sub(info.ModTime()) < maxAge {
				continue
			}
			if err := Remove(cacheRoot, a.Name(), strings.TrimSuffix(draftID, ".meta")); err != nil {
				errs = append(errs, err)
			}
		}
	}
	return errs
}

func dirExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

var (
	pathsMu sync.Mutex
	busy    = map[string]chan struct{}{} // draft folders an Ensure or Remove is working on
)

// lockPath serializes the work on one draft's folder within the runner.
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
