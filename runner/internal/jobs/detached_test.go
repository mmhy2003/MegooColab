package jobs

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// A worktree whose HEAD is detached when a read-only run starts has no branch
// to compare, so a commit on the task branch followed by a detach would go
// unseen: the run does not start.
func TestReadOnlyRunOnADetachedHeadFailsBeforeTheAdapterStarts(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.startRun("run-d1", "MEG-50", "workspace")
	e.finished("run-d1")
	_ = os.Remove(e.report)
	if out, err := exec.Command("git", "-C", e.worktree("MEG-50"), "checkout", "-q", "--detach").CombinedOutput(); err != nil {
		t.Fatalf("%v %s", err, out)
	}
	e.startRun("run-d2", "MEG-50", "read_only")
	rf := e.finished("run-d2")
	if rf.Outcome != "failed" || rf.Error == nil || *rf.Error != "git_state_unreadable" {
		t.Fatalf("finished = %+v", rf)
	}
	if _, err := os.Stat(e.report); err == nil {
		t.Fatal("the adapter was started")
	}
	log, err := os.ReadFile(filepath.Join(e.cache, "logs", "run-d2.log"))
	if err != nil || !strings.Contains(string(log), "detached") {
		t.Fatalf("the run log must say HEAD is detached: %q %v", log, err)
	}
}
