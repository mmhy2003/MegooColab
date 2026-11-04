package jobs

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

const testCron = "5e1a2b3c-0000-4000-8000-000000000001"

func gitOut(t *testing.T, dir string, args ...string) string {
	t.Helper()
	out, err := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t"}, args...)...).CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

// withOrigin gives the env's repository an origin whose default branch moved one commit ahead of the local
// checkout; it returns the branch, origin's new head, and the origin's folder.
func (e *env) withOrigin(t *testing.T) (branch, head, origin string) {
	branch = gitOut(t, e.repo, "symbolic-ref", "--short", "HEAD")
	origin = filepath.Join(t.TempDir(), "origin.git")
	gitOut(t, e.repo, "clone", "-q", "--bare", e.repo, origin)
	gitOut(t, e.repo, "remote", "add", "origin", origin)
	work := filepath.Join(t.TempDir(), "work")
	gitOut(t, e.repo, "clone", "-q", origin, work)
	if err := os.WriteFile(filepath.Join(work, "ahead.txt"), []byte("ahead\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	gitOut(t, work, "add", ".")
	gitOut(t, work, "commit", "-q", "-m", "ahead")
	gitOut(t, work, "push", "-q", "origin", "HEAD:"+branch)
	return branch, gitOut(t, work, "rev-parse", "HEAD"), origin
}

func (e *env) cronFolder() string { return filepath.Join(e.cache, "crons", "agent-1", testCron) }

func (e *env) startCronRun(runID, branch string) {
	e.startRunWith(runID, "CRN-5e1a2b3c0000", func(rs *protocol.RunStart) {
		rs.LocalPath = ""
		rs.Role = "cron"
		rs.Cron = &protocol.RunCron{ID: testCron, Branch: branch}
	})
}

func TestCronRunWorksOnTheDefaultBranchInItsOwnWorktree(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"checked"}]`, 1, t.TempDir())
	branch, head, _ := e.withOrigin(t)
	e.startCronRun("run-1", branch)
	rf := e.finished("run-1")
	if rf.Outcome != "completed" || rf.GitBefore == nil || rf.GitBefore.Head == nil || *rf.GitBefore.Head != head {
		t.Fatalf("finished = %+v, want git_before at origin's %s", rf, head)
	}
	if r := e.readReport(); r.Cwd != e.cronFolder() {
		t.Fatalf("cwd = %q, want %q", r.Cwd, e.cronFolder())
	}
}

func TestCronRunChangesAreThrownAway(t *testing.T) {
	cache := t.TempDir()
	junk := filepath.Join(cache, "crons", "agent-1", testCron, "junk.txt")
	e := newEnvWithCache(t, `[{"write":{"path":`+jsonStr(junk)+`,"content":"x"}},{"say":"done"}]`, 1, cache)
	branch, _, _ := e.withOrigin(t)
	e.startCronRun("run-1", branch)
	if rf := e.finished("run-1"); rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	if _, err := os.Stat(junk); !os.IsNotExist(err) {
		t.Fatalf("the run's change was kept: %v", err)
	}
}

func TestCronRunCommitIsReported(t *testing.T) {
	cache := t.TempDir()
	file := filepath.Join(cache, "crons", "agent-1", testCron, "new.txt")
	e := newEnvWithCache(t, `[{"write":{"path":`+jsonStr(file)+`,"content":"x"}},{"commit":{"message":"oops","all":true}}]`, 1, cache)
	branch, head, _ := e.withOrigin(t)
	e.startCronRun("run-1", branch)
	rf := e.finished("run-1")
	if rf.GitAfter == nil || rf.GitAfter.Head == nil || *rf.GitAfter.Head == head {
		t.Fatalf("git_after = %+v, want the agent's commit", rf.GitAfter)
	}
	if got := gitOut(t, e.cronFolder(), "rev-parse", "HEAD"); got != head {
		t.Fatalf("the worktree was left at %s, want it reset to %s", got, head)
	}
}

func TestCronFetchFailureUsesTheLastFetchedCommit(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"checked"}]`, 2, t.TempDir())
	branch, head, origin := e.withOrigin(t)
	e.startCronRun("run-1", branch)
	e.finished("run-1")
	if err := os.RemoveAll(origin); err != nil { // origin unreachable from now on
		t.Fatal(err)
	}
	e.startCronRun("run-2", branch)
	rf := e.finished("run-2")
	if rf.Outcome != "completed" || rf.GitBefore == nil || *rf.GitBefore.Head != head {
		t.Fatalf("finished = %+v, want the last fetched %s", rf, head)
	}
}
