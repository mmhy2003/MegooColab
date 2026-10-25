package jobs

import (
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/gitstate"
	"github.com/mmhy2003/megoocolab/runner/internal/testutil"
)

// failLsFilesAfter makes every git call from now on run through fakeGit, with
// the first allow ls-files calls working.
func failLsFilesAfter(t *testing.T, allow int) {
	t.Helper()
	t.Setenv("FAKEGIT_ALLOW_LS", strconv.Itoa(allow))
	t.Setenv("FAKEGIT_COUNTER", filepath.Join(t.TempDir(), "count"))
	t.Cleanup(gitstate.OverrideForTest(testutil.BuildFakeGit(t), time.Minute))
}

func TestReadOnlyRunFailsWhenItsBeforeStateIsUnreadable(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"never"}]`, 1, t.TempDir())
	failLsFilesAfter(t, 0)
	e.startRun("run-nb", "MEG-40", "read_only")
	rf := e.finished("run-nb")
	if rf.Outcome != "failed" || rf.Error == nil || *rf.Error != "git_state_unreadable" {
		t.Fatalf("finished = %+v", rf)
	}
	if _, err := os.Stat(e.report); err == nil {
		t.Fatal("the adapter was started")
	}
}

func TestAfterCaptureFailureStillSendsADirtyGitAfter(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	failLsFilesAfter(t, 2) // the before capture works, the after capture does not
	e.startRun("run-af", "MEG-41", "read_only")
	rf := e.finished("run-af")
	if rf.Outcome != "completed" || rf.GitBefore == nil || rf.GitAfter == nil || !rf.GitAfter.Dirty {
		t.Fatalf("finished = %+v after=%+v", rf, rf.GitAfter)
	}
}

func TestWithoutABeforeStateTheAfterStateIsOmitted(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	failLsFilesAfter(t, 0)
	e.startRun("run-w", "MEG-42", "workspace")
	rf := e.finished("run-w")
	if rf.Outcome != "completed" || rf.GitBefore != nil || rf.GitAfter != nil {
		t.Fatalf("finished = %+v", rf)
	}
}
