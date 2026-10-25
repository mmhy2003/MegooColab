package gitstate

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
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
	var admins []string
	for _, e := range entries {
		admin := filepath.Join(common, "worktrees", e.Name())
		back, err := os.ReadFile(filepath.Join(admin, "gitdir"))
		if err == nil && sameFile(strings.TrimSpace(string(back)), dotgit) {
			admins = append(admins, admin)
		}
	}
	switch len(admins) {
	case 0:
		return pinned{}, errors.New("the worktree is not registered with its repository")
	case 1:
	default:
		return pinned{}, errors.New("more than one git dir is registered for the worktree")
	}
	p := pinned{admins[0], common}
	if err := checkPin(worktree, p); err != nil {
		return pinned{}, err
	}
	pointer, err := os.ReadFile(dotgit)
	target, ok := strings.CutPrefix(strings.TrimSpace(string(pointer)), "gitdir:")
	target = strings.TrimSpace(target)
	if !filepath.IsAbs(target) {
		target = filepath.Join(worktree, target)
	}
	if err != nil || !ok || !sameFile(target, p.gitdir) {
		return pinned{}, errors.New("the worktree's .git does not point at its registered git dir")
	}
	return p, nil
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

// pinFor returns the pin of a worktree. A worktree nobody pinned is an error:
// reading it from its own .git file would trust what the agent can write. Only
// tests (allowImplicitPin) pin a worktree from itself.
func pinFor(worktree string) (pinned, error) {
	key := filepath.Clean(worktree)
	v, ok := pins.Load(key)
	if !ok {
		if !allowImplicitPin {
			return pinned{}, errors.New("the worktree's git dir was never pinned")
		}
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

// branchRef returns the ref HEAD points at, or "" for a detached HEAD. Only
// git's exit status 1 ("not a symbolic ref") counts as detached.
func branchRef(dir string) (string, error) {
	out, err := wgit(dir, "symbolic-ref", "-q", "HEAD")
	if err != nil {
		if exitIsOne(err) {
			return "", nil
		}
		return "", err
	}
	return strings.TrimSpace(out), nil
}

// hiddenGitFiles hashes the files in the git dirs that decide what status
// shows, or run code while it does: the shared config and attributes, the
// worktree's own config, and the exclude file without the runner's own line.
// All are read through the pinned dirs. A run that changes any of them is
// dirty: a clean filter plus an attribute hides a same-size edit.
func hiddenGitFiles(dir string) (string, error) {
	p, err := pinFor(dir)
	if err != nil {
		return "", err
	}
	h := sha256.New()
	for _, f := range []string{
		filepath.Join(p.common, "config"),
		filepath.Join(p.common, "info", "attributes"),
		filepath.Join(p.gitdir, "config.worktree"),
		filepath.Join(p.common, "info", "exclude"),
	} {
		b, err := os.ReadFile(f)
		switch {
		case errors.Is(err, os.ErrNotExist):
			b = []byte("<absent>")
		case err != nil:
			return "", err
		}
		if filepath.Base(f) == "exclude" {
			var keep []string
			for _, l := range strings.Split(string(b), "\n") {
				if strings.TrimSpace(l) != excludeLine {
					keep = append(keep, l)
				}
			}
			b = []byte(strings.Join(keep, "\n"))
		}
		fmt.Fprintf(h, "%s:%d:", filepath.Base(f), len(b))
		h.Write(b)
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// wgitNoFilters is wgit with every filter driver defined in the pinned config
// switched off (clean, smudge, process, required), so that a filter the agent
// configured never runs inside the runner's status call and cannot make a
// changed file look unchanged. This narrows the earlier ruling that filters
// stay enabled: that still holds for checkout (worktree add), not for the
// runner's own capture.
func wgitNoFilters(dir string, args ...string) (string, error) {
	out, err := wgit(dir, "config", "-z", "--get-regexp", "^filter[.]")
	if err != nil && !exitIsOne(err) {
		return "", err
	}
	return wgit(dir, append(filterOffArgs(out), args...)...)
}

// filterOffArgs builds the -c options that switch off every filter driver in
// `config -z --get-regexp` output ("key", newline, "value", NUL), except stock
// Git LFS. LFS stays on only while its process filter is exactly
// `git-lfs filter-process` and its clean and smudge, if set, are exactly the
// stock `git-lfs clean -- %f` and `git-lfs smudge -- %f`: its pointer files are
// how an LFS repository's files appear in status, and switching it off would
// make every LFS file look modified. Anything else under the name lfs is
// neutralised like any other driver.
func filterOffArgs(out string) []string {
	vals := map[string]map[string]string{}
	var names []string
	for _, ent := range strings.Split(out, "\x00") {
		key, val, _ := strings.Cut(ent, "\n")
		rest, ok := strings.CutPrefix(key, "filter.")
		i := strings.LastIndex(rest, ".")
		if !ok || i <= 0 {
			continue
		}
		name, field := rest[:i], strings.ToLower(rest[i+1:])
		if vals[name] == nil {
			vals[name] = map[string]string{}
			names = append(names, name)
		}
		vals[name][field] = val
	}
	var off []string
	for _, name := range names {
		v := vals[name]
		if name == "lfs" && v["process"] == "git-lfs filter-process" &&
			(v["clean"] == "" || v["clean"] == "git-lfs clean -- %f") &&
			(v["smudge"] == "" || v["smudge"] == "git-lfs smudge -- %f") {
			continue
		}
		for _, f := range []string{"clean", "smudge", "process"} {
			off = append(off, "-c", "filter."+name+"."+f+"=")
		}
		off = append(off, "-c", "filter."+name+".required=false")
	}
	return off
}

// OnBranchPrefix reports whether HEAD was on a local branch whose name starts
// with prefix when the snapshot was taken.
func (s Snapshot) OnBranchPrefix(prefix string) bool {
	return strings.HasPrefix(s.branchRef, "refs/heads/"+prefix)
}

// Branch is the ref HEAD was on when the snapshot was taken, "" when detached.
func (s Snapshot) Branch() string { return s.branchRef }

// branchTips lists the tips of the local branches under refs/heads/<prefix>:
// the task's branches. A read-only run may start on any of them (an earlier run
// can leave HEAD on a leftover branch), so a commit on another of them, then a
// switch back, has to show.
func branchTips(dir, prefix string) (map[string]string, error) {
	tips := map[string]string{}
	if prefix == "" {
		return tips, nil
	}
	out, err := wgit(dir, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/"+prefix+"*")
	if err != nil {
		return nil, err
	}
	for _, l := range strings.Split(out, "\n") {
		if ref, sha, ok := strings.Cut(strings.TrimSpace(l), " "); ok {
			tips[ref] = sha
		}
	}
	return tips, nil
}

// allowImplicitPin lets tests use a worktree nobody pinned. Production never sets it.
var allowImplicitPin = false
