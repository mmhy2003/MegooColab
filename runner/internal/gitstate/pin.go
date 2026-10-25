package gitstate

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// pinned is a worktree's git dirs, fixed when the run started: the per-worktree
// admin dir and the common dir.
type pinned struct{ gitdir, common string }

var pins sync.Map // filepath.Clean(worktree) -> pinned

// Pin fixes the git dirs the runner reads for a worktree. The manager calls it
// right after worktree.Ensure, before any agent runs, and the dirs are derived
// from repo (the bound repository, which the agent does not control) and never
// from the content of the worktree's .git: the common dir is repo's, the admin
// dir is the entry <common>/worktrees/<name> whose gitdir file names
// <worktree>/.git and whose commondir names that common dir. It is an error
// when the worktree's .git file does not point at that admin dir. Pin is the
// only way a pin is replaced (a recreated worktree is pinned again by the next
// run); wgit never re-pins. A plain repository (repo is the worktree) pins its
// own .git.
func Pin(worktree, repo string) error {
	key := filepath.Clean(worktree)
	p, err := derivePin(worktree, repo)
	if err != nil {
		pins.Delete(key)
		return err
	}
	pins.Store(key, p)
	return nil
}

func derivePin(worktree, repo string) (pinned, error) {
	out, err := git(repo, "rev-parse", "--git-common-dir")
	if err != nil {
		return pinned{}, err
	}
	common := strings.TrimSpace(out)
	if !filepath.IsAbs(common) {
		common = filepath.Join(repo, common)
	}
	common = filepath.Clean(common)
	dotgit := filepath.Join(worktree, ".git")
	if sameFile(common, dotgit) { // a plain repository
		return pinned{common, common}, nil
	}
	entries, _ := os.ReadDir(filepath.Join(common, "worktrees"))
	for _, e := range entries {
		admin := filepath.Join(common, "worktrees", e.Name())
		back, err := os.ReadFile(filepath.Join(admin, "gitdir"))
		if err != nil || !sameFile(strings.TrimSpace(string(back)), dotgit) {
			continue
		}
		p := pinned{admin, common}
		if err := checkPin(worktree, p); err != nil {
			return pinned{}, err
		}
		pointer, err := os.ReadFile(dotgit)
		target, ok := strings.CutPrefix(strings.TrimSpace(string(pointer)), "gitdir:")
		target = strings.TrimSpace(target)
		if !filepath.IsAbs(target) {
			target = filepath.Join(worktree, target)
		}
		if err != nil || !ok || !sameFile(target, admin) {
			return pinned{}, errors.New("the worktree's .git does not point at its registered git dir")
		}
		return p, nil
	}
	return pinned{}, errors.New("the worktree is not registered with its repository")
}

// checkPin re-validates a pin before it is used: the admin dir is still there,
// its commondir still names the pinned common dir and its gitdir file still
// names the worktree. An agent can write to all of these; any mismatch is an
// error, which makes the capture fail closed.
func checkPin(worktree string, p pinned) error {
	if !isDir(p.gitdir) {
		return errors.New("the pinned git dir is gone")
	}
	dotgit := filepath.Join(worktree, ".git")
	if sameFile(p.gitdir, p.common) { // a plain repository
		if !sameFile(p.common, dotgit) {
			return errors.New("the pinned git dir is no longer the worktree's")
		}
		return nil
	}
	cd, err := os.ReadFile(filepath.Join(p.gitdir, "commondir"))
	if err != nil {
		return errors.New("the pinned git dir has no commondir")
	}
	c := strings.TrimSpace(string(cd))
	if !filepath.IsAbs(c) {
		c = filepath.Join(p.gitdir, c)
	}
	if !sameFile(c, p.common) {
		return errors.New("the pinned git dir's commondir was changed")
	}
	back, err := os.ReadFile(filepath.Join(p.gitdir, "gitdir"))
	if err != nil || !sameFile(strings.TrimSpace(string(back)), dotgit) {
		return errors.New("the pinned git dir no longer refers to the worktree")
	}
	return nil
}

// pinFor returns the pin of a worktree. A worktree nobody pinned (tests, and
// callers before Pin) is pinned from itself, once: that trusts its .git file.
func pinFor(worktree string) (pinned, error) {
	key := filepath.Clean(worktree)
	v, ok := pins.Load(key)
	if !ok {
		if err := Pin(worktree, worktree); err != nil {
			return pinned{}, err
		}
		v, _ = pins.Load(key)
	}
	p := v.(pinned)
	return p, checkPin(worktree, p)
}

// wgit is git for a worktree, pinned to its git dir and common dir, also in the
// environment so that the admin dir's commondir file is not consulted.
func wgit(worktree string, args ...string) (string, error) {
	p, err := pinFor(worktree)
	if err != nil {
		return "", err
	}
	return gitIn(context.Background(), timeout, worktree, "", []string{"GIT_COMMON_DIR=" + p.common},
		append([]string{"--git-dir=" + p.gitdir, "--work-tree=" + worktree}, args...)...)
}

// branchTip returns the ref HEAD points at and the commit it points at. Both are
// "" for a detached HEAD, the tip for an unborn branch. Only git's exit status 1
// ("not a symbolic ref", "no such ref") counts as absent.
func branchTip(dir string) (ref, tip string, err error) {
	out, err := wgit(dir, "symbolic-ref", "-q", "HEAD")
	if err != nil {
		if exitIsOne(err) {
			return "", "", nil
		}
		return "", "", err
	}
	ref = strings.TrimSpace(out)
	out, err = wgit(dir, "rev-parse", "--verify", "-q", ref)
	if err != nil {
		if exitIsOne(err) {
			return ref, "", nil
		}
		return "", "", err
	}
	return ref, strings.TrimSpace(out), nil
}
