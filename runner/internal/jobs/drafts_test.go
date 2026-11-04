package jobs

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

const testDraft = "5f1d2c3b-aaaa-4bbb-8ccc-0d1e2f3a4b5c"

func (e *env) draftFolder() string { return filepath.Join(e.cache, "drafts", "agent-1", testDraft) }

func (e *env) startDraftRun(runID, projectKey string) {
	e.startRunWith(runID, "KBD-5f1d2c3baaaa", func(rs *protocol.RunStart) {
		rs.Task.ProjectKey = projectKey
		rs.LocalPath = ""
		rs.Policy = "read_only"
		rs.Role = "kb_draft"
		rs.Draft = &protocol.RunDraft{ID: testDraft}
	})
}

func TestDraftRunWorksInDraftFolder(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"drafted"}]`, 1, t.TempDir())
	e.startDraftRun("run-1", "")
	if rf := e.finished("run-1"); rf.Outcome != "completed" || rf.GitBefore != nil {
		t.Fatalf("finished = %+v", rf)
	}
	if r := e.readReport(); r.Cwd != e.draftFolder() {
		t.Fatalf("cwd = %q, want the draft folder %q", r.Cwd, e.draftFolder())
	}
	if entries, _ := os.ReadDir(e.draftFolder()); len(entries) != 0 {
		t.Fatalf("a team draft's folder holds %d entries, want none", len(entries))
	}
}

func TestProjectDraftRunWorksInADetachedWorktree(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"drafted"}]`, 1, t.TempDir())
	e.startDraftRun("run-1", "MEG")
	if rf := e.finished("run-1"); rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	if r := e.readReport(); r.Cwd != e.draftFolder() {
		t.Fatalf("cwd = %q, want %q", r.Cwd, e.draftFolder())
	}
	if err := exec.Command("git", "-C", e.draftFolder(), "symbolic-ref", "-q", "HEAD").Run(); err == nil {
		t.Fatal("the draft's worktree is on a branch, want detached")
	}
}

func TestDraftDoneRemovesFolder(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"drafted"}]`, 1, t.TempDir())
	e.startDraftRun("run-1", "")
	e.finished("run-1")
	if _, err := os.Stat(e.draftFolder()); err != nil {
		t.Fatalf("no draft folder after the run: %v", err)
	}
	if err := e.srv.Send(protocol.DraftDone{Type: protocol.TypeDraftDone, AgentID: "agent-1", DraftID: testDraft}); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(e.draftFolder()); os.IsNotExist(err) {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("draft_done left the draft's folder")
}
