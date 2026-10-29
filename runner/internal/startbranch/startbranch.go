// Package startbranch decides which branch a task's branch starts from
// (Branch from) and brings it up to date from origin first, so an agent never
// builds on whatever happens to be checked out in the developer's folder.
package startbranch

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/url"
	"strings"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/gitstate"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// Stable failure codes: the server keeps them as the run's reason.
var (
	ErrStartBranchMissing   = errors.New("start_branch_missing")
	ErrRepositoryNotMatched = errors.New("repository_not_matched")
	// origin could not be reached and there is no copy of the branch to start from
	ErrStartBranchFetchFailed = errors.New("start_branch_fetch_failed")
)

// FetchTimeout bounds the fetch of the start branch. A var for tests.
var FetchTimeout = 5 * time.Minute

// Result is where to start. StartPoint "" means HEAD, as before Branch from.
// Report says the server should record StartBranch and DefaultBranch.
type Result struct {
	StartPoint    string
	StartBranch   string
	DefaultBranch string
	RepositoryURL string
	Report        bool
}

// NormalizeURL reduces a remote URL to a lower-cased "host/path": no scheme,
// credentials, port, trailing "/" or ".git". scp-like "git@host:owner/repo"
// is understood. A local path (a remote on disk) stays a path, with forward
// slashes.
func NormalizeURL(u string) string {
	u = strings.TrimSpace(u)
	trim := func(p string) string { return strings.TrimSuffix(strings.TrimRight(p, "/"), ".git") }
	if i := strings.Index(u, "://"); i >= 0 {
		parsed, err := url.Parse(u)
		if err != nil || parsed.Hostname() == "" {
			return ""
		}
		path := trim(strings.Trim(parsed.Path, "/"))
		if path == "" {
			return ""
		}
		return strings.ToLower(parsed.Hostname() + "/" + path)
	}
	// scp-like: [user@]host:path, where host is more than a drive letter and holds no slash
	if colon := strings.Index(u, ":"); colon > 1 && !strings.ContainsAny(u[:colon], `/\`) {
		host := u[strings.Index(u, "@")+1 : colon]
		if path := trim(strings.Trim(u[colon+1:], "/")); host != "" && path != "" {
			return strings.ToLower(host + "/" + path)
		}
		return ""
	}
	if u == "" {
		return ""
	}
	return strings.ToLower(trim(strings.ReplaceAll(u, `\`, "/")))
}

func git(repo string, args ...string) (string, error) {
	out, err := gitstate.Run(repo, args...)
	return strings.TrimSpace(out), err
}

func hasRef(repo, ref string) bool {
	_, err := git(repo, "show-ref", "--verify", "--quiet", ref)
	return err == nil
}

// matchRepository is the project repository the folder's origin belongs to;
// with no match, the only repository if there is exactly one.
func matchRepository(origin string, repos []protocol.RunBranchRepo) *protocol.RunBranchRepo {
	if want := NormalizeURL(origin); want != "" {
		for i := range repos {
			if NormalizeURL(repos[i].URL) == want {
				return &repos[i]
			}
		}
	}
	if len(repos) == 1 {
		return &repos[0]
	}
	return nil
}

// Resolve decides the start branch for a task branch about to be created, and
// fetches it. Every fallback it takes is written to logw.
func Resolve(ctx context.Context, logw io.Writer, repo string, spec *protocol.RunBranch) (Result, error) {
	if logw == nil {
		logw = io.Discard
	}
	if spec == nil {
		return Result{}, nil
	}
	origin, err := git(repo, "remote", "get-url", "origin")
	if err != nil {
		origin = ""
	}
	if spec.StartBranch != "" { // recorded when the branch was first created
		point, err := startPoint(ctx, logw, repo, origin, spec.StartBranch)
		if err != nil {
			return Result{}, err
		}
		return Result{StartPoint: point, StartBranch: spec.StartBranch}, nil
	}
	match := matchRepository(origin, spec.Repositories)
	if spec.BranchFrom != "" {
		if match == nil {
			fmt.Fprintf(logw, "runner: origin %q matches none of the project's %d repositories\n", origin, len(spec.Repositories))
			return Result{}, ErrRepositoryNotMatched
		}
		point, err := startPoint(ctx, logw, repo, origin, spec.BranchFrom)
		if err != nil {
			return Result{}, err
		}
		fmt.Fprintf(logw, "runner: starting from %s (Branch from), repository %s\n", point, match.URL)
		return Result{StartPoint: point, StartBranch: spec.BranchFrom, DefaultBranch: match.DefaultBranch,
			RepositoryURL: match.URL, Report: true}, nil
	}
	if match == nil {
		fmt.Fprintf(logw, "runner: no project repository matches origin %q; starting from HEAD\n", origin)
		return headResult(repo), nil
	}
	res := Result{StartBranch: match.DefaultBranch, DefaultBranch: match.DefaultBranch, RepositoryURL: match.URL, Report: true}
	point, err := startPoint(ctx, logw, repo, origin, match.DefaultBranch)
	switch {
	case err == nil:
		res.StartPoint = point
	case errors.Is(err, ErrStartBranchMissing):
		// confirmed absent (not merely unreachable): the stored default may be the unchecked "main" of a
		// repository whose branch is master
		var point string
		var e error = ErrStartBranchMissing
		actual := ""
		if b, e2 := git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"); e2 == nil && strings.HasPrefix(b, "origin/") {
			actual = strings.TrimPrefix(b, "origin/")
			point, e = startPoint(ctx, logw, repo, origin, actual)
		}
		if e == nil {
			fmt.Fprintf(logw, "runner: default branch %q not found; using origin's default %q\n", match.DefaultBranch, actual)
			res.StartPoint, res.StartBranch, res.DefaultBranch = point, actual, actual
		} else if head := headResult(repo); head.Report {
			fmt.Fprintf(logw, "runner: default branch %q not found; starting from the checked-out %q\n", match.DefaultBranch, head.StartBranch)
			head.RepositoryURL = match.URL
			res = head
		} else {
			fmt.Fprintf(logw, "runner: default branch %q not found; starting from HEAD\n", match.DefaultBranch)
			return Result{}, nil
		}
	default:
		return Result{}, err
	}
	fmt.Fprintf(logw, "runner: starting from %s, repository %s\n", res.StartPoint, match.URL)
	return res, nil
}

// headResult is "start from HEAD", reported as the checked-out branch so the
// server records where the work started; nothing when HEAD is detached.
func headResult(repo string) Result {
	head, err := git(repo, "symbolic-ref", "--short", "HEAD")
	if err != nil || head == "" {
		return Result{}
	}
	return Result{StartBranch: head, DefaultBranch: head, Report: true}
}

// startPoint fetches branch from origin and returns origin/<branch>. A branch
// origin does not have (or a folder without origin) falls back to the local
// branch, else ErrStartBranchMissing. An origin that cannot be reached falls
// back to the last fetched origin/<branch>, then the local branch, else
// ErrStartBranchFetchFailed: never to a different branch.
func startPoint(ctx context.Context, logw io.Writer, repo, origin, branch string) (string, error) {
	why := "the folder has no origin remote"
	if origin != "" {
		refspec := "+refs/heads/" + branch + ":refs/remotes/origin/" + branch
		_, err := gitstate.RunContext(ctx, FetchTimeout, repo, "fetch", "--no-tags", "origin", refspec)
		switch {
		case err == nil:
			return "origin/" + branch, nil
		case ctx.Err() != nil:
			return "", ctx.Err()
		case !strings.Contains(err.Error(), "couldn't find remote ref"):
			// unreachable (offline, no credentials): the branch may well exist there
			if hasRef(repo, "refs/remotes/origin/"+branch) {
				fmt.Fprintf(logw, "runner: could not fetch %s (%v); using the last fetched origin/%s\n", branch, err, branch)
				return "origin/" + branch, nil
			}
			if hasRef(repo, "refs/heads/"+branch) {
				fmt.Fprintf(logw, "runner: using the local %s: %v\n", branch, err)
				return branch, nil
			}
			fmt.Fprintf(logw, "runner: could not fetch %s and there is no copy of it: %v\n", branch, err)
			return "", ErrStartBranchFetchFailed
		}
		why = "origin has no branch " + branch
	}
	if hasRef(repo, "refs/heads/"+branch) {
		fmt.Fprintf(logw, "runner: using the local %s: %s\n", branch, why)
		return branch, nil
	}
	fmt.Fprintf(logw, "runner: branch %q not found on origin or locally: %s\n", branch, why)
	return "", ErrStartBranchMissing
}

// Remember stores where the task branch started in the repository's config
// (branch.<name>.megoocolab-*), so a later run can report it again if the
// first report never reached the server.
func Remember(repo, branch string, res Result) error {
	for k, v := range map[string]string{"start": res.StartBranch, "default": res.DefaultBranch, "repository": res.RepositoryURL} {
		if _, err := git(repo, "config", "branch."+branch+".megoocolab-"+k, v); err != nil {
			return err
		}
	}
	return nil
}

// Recall reads what Remember stored for branch.
func Recall(repo, branch string) (Result, bool) {
	get := func(k string) string {
		v, _ := git(repo, "config", "--get", "branch."+branch+".megoocolab-"+k)
		return v
	}
	start := get("start")
	if start == "" {
		return Result{}, false
	}
	return Result{StartBranch: start, DefaultBranch: get("default"), RepositoryURL: get("repository"), Report: true}, true
}
