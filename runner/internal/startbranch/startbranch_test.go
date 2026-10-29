package startbranch

import (
	"bytes"
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

func runGit(t *testing.T, dir string, args ...string) string {
	t.Helper()
	out, err := exec.Command("git", append([]string{"-C", dir}, args...)...).CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

func commit(t *testing.T, dir, file string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, file), []byte(file), 0o644); err != nil {
		t.Fatal(err)
	}
	runGit(t, dir, "add", ".")
	runGit(t, dir, "commit", "-q", "-m", file)
}

func configure(t *testing.T, dir string) {
	runGit(t, dir, "config", "user.name", "T")
	runGit(t, dir, "config", "user.email", "t@example.com")
	runGit(t, dir, "config", "commit.gpgsign", "false")
}

// world is a bare origin whose HEAD is `head`, with branches main and develop,
// and a clone of it (the developer's folder). It returns origin, clone and a
// scratch repo that can push to origin.
func world(t *testing.T, head string) (origin, clone, pusher string) {
	t.Helper()
	origin = filepath.Join(t.TempDir(), "pay.git")
	runGit(t, filepath.Dir(origin), "init", "-q", "--bare", "-b", head, origin)
	pusher = t.TempDir()
	runGit(t, pusher, "init", "-q", "-b", head)
	configure(t, pusher)
	commit(t, pusher, "a.txt")
	runGit(t, pusher, "remote", "add", "origin", origin)
	runGit(t, pusher, "push", "-q", "origin", head)
	for _, b := range []string{"main", "develop"} {
		if b != head {
			runGit(t, pusher, "push", "-q", "origin", head+":"+b)
		}
	}
	clone = filepath.Join(t.TempDir(), "clone")
	runGit(t, filepath.Dir(clone), "clone", "-q", origin, clone)
	configure(t, clone)
	return origin, clone, pusher
}

func repos(pairs ...string) []protocol.RunBranchRepo {
	var out []protocol.RunBranchRepo
	for i := 0; i+1 < len(pairs); i += 2 {
		out = append(out, protocol.RunBranchRepo{URL: pairs[i], DefaultBranch: pairs[i+1]})
	}
	return out
}

func TestNormalizeURL(t *testing.T) {
	for _, u := range []string{
		"https://github.com/Acme/Pay.git", "git@github.com:acme/pay.git", "ssh://git@github.com:22/acme/pay",
		"https://user:tok@github.com/acme/pay/",
	} {
		if got := NormalizeURL(u); got != "github.com/acme/pay" {
			t.Errorf("NormalizeURL(%q) = %q", u, got)
		}
	}
	if got := NormalizeURL("https://gitea.local/x/y"); got != "gitea.local/x/y" {
		t.Errorf("gitea: %q", got)
	}
	if got := NormalizeURL(`C:\Repos\Pay.git`); got != "c:/repos/pay" {
		t.Errorf("windows path: %q", got)
	}
	if got := NormalizeURL("/some/local/path/"); got != "/some/local/path" {
		t.Errorf("local path: %q", got)
	}
}

func TestResolveDefaultFromMatchedRepository(t *testing.T) {
	origin, clone, _ := world(t, "main")
	spec := &protocol.RunBranch{Repositories: repos("https://example.com/other", "main", origin, "develop")}
	res, err := Resolve(context.Background(), nil, clone, spec)
	if err != nil {
		t.Fatal(err)
	}
	want := Result{StartPoint: "origin/develop", StartBranch: "develop", DefaultBranch: "develop", RepositoryURL: origin, Report: true}
	if res != want {
		t.Fatalf("got %+v, want %+v", res, want)
	}
}

func TestResolveBranchFromFetchesLatest(t *testing.T) {
	origin, clone, pusher := world(t, "main")
	commit(t, pusher, "b.txt")
	runGit(t, pusher, "push", "-q", "origin", "main")
	latest := runGit(t, pusher, "rev-parse", "HEAD")
	spec := &protocol.RunBranch{BranchFrom: "main", Repositories: repos(origin, "develop")}
	res, err := Resolve(context.Background(), nil, clone, spec)
	if err != nil {
		t.Fatal(err)
	}
	if res.StartPoint != "origin/main" || res.StartBranch != "main" || res.DefaultBranch != "develop" || !res.Report {
		t.Fatalf("got %+v", res)
	}
	if got := runGit(t, clone, "rev-parse", "origin/main"); got != latest {
		t.Fatalf("origin/main = %s, want the pushed %s", got, latest)
	}
}

func TestResolveBranchFromWithoutMatchFails(t *testing.T) {
	_, clone, _ := world(t, "main")
	spec := &protocol.RunBranch{BranchFrom: "main", Repositories: repos("https://a.example/x", "main", "https://b.example/y", "main")}
	if _, err := Resolve(context.Background(), nil, clone, spec); !errors.Is(err, ErrRepositoryNotMatched) {
		t.Fatalf("err = %v", err)
	}
}

func TestResolveSingleRepositoryUsedWithoutMatch(t *testing.T) {
	_, clone, _ := world(t, "main")
	spec := &protocol.RunBranch{Repositories: repos("https://github.com/acme/elsewhere", "develop")}
	res, err := Resolve(context.Background(), nil, clone, spec)
	if err != nil || res.StartPoint != "origin/develop" || res.DefaultBranch != "develop" {
		t.Fatalf("got %+v, %v", res, err)
	}
}

func TestResolveNoRepositoriesKeepsHead(t *testing.T) {
	_, clone, _ := world(t, "main")
	res, err := Resolve(context.Background(), nil, clone, &protocol.RunBranch{})
	if err != nil || res != (Result{}) {
		t.Fatalf("got %+v, %v", res, err)
	}
	if res, err := Resolve(context.Background(), nil, clone, nil); err != nil || res != (Result{}) {
		t.Fatalf("nil spec: %+v, %v", res, err)
	}
}

func TestResolveExplicitMissingFails(t *testing.T) {
	origin, clone, _ := world(t, "main")
	spec := &protocol.RunBranch{BranchFrom: "hotfix-base", Repositories: repos(origin, "develop")}
	if _, err := Resolve(context.Background(), nil, clone, spec); !errors.Is(err, ErrStartBranchMissing) {
		t.Fatalf("err = %v", err)
	}
}

func TestResolveImplicitDefaultFallsBackToOriginHead(t *testing.T) {
	origin, clone, _ := world(t, "master")
	runGit(t, origin, "branch", "-D", "main")
	var log bytes.Buffer
	res, err := Resolve(context.Background(), &log, clone, &protocol.RunBranch{Repositories: repos(origin, "main")})
	if err != nil {
		t.Fatal(err)
	}
	if res.StartPoint != "origin/master" || res.StartBranch != "master" || res.DefaultBranch != "master" || !res.Report {
		t.Fatalf("got %+v", res)
	}
	if !strings.Contains(log.String(), `default branch "main" not found`) {
		t.Fatalf("log: %s", log.String())
	}
}

func TestResolveOfflineUsesLocalBranch(t *testing.T) {
	origin, clone, _ := world(t, "main")
	runGit(t, clone, "branch", "develop", "origin/develop")
	if err := os.RemoveAll(origin); err != nil {
		t.Fatal(err)
	}
	var log bytes.Buffer
	res, err := Resolve(context.Background(), &log, clone, &protocol.RunBranch{Repositories: repos(origin, "develop")})
	if err != nil || res.StartPoint != "develop" || res.StartBranch != "develop" {
		t.Fatalf("got %+v, %v", res, err)
	}
	if !strings.Contains(log.String(), "using the local develop") {
		t.Fatalf("log: %s", log.String())
	}
}

func TestResolveRecordedStartNotReported(t *testing.T) {
	origin, clone, _ := world(t, "main")
	spec := &protocol.RunBranch{BranchFrom: "develop", StartBranch: "main", Repositories: repos(origin, "develop")}
	res, err := Resolve(context.Background(), nil, clone, spec)
	if err != nil || res.StartPoint != "origin/main" || res.StartBranch != "main" || res.Report {
		t.Fatalf("got %+v, %v", res, err)
	}
}
