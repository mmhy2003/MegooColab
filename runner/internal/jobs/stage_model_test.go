package jobs

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// runOn runs a workflow run with a model choice (nil: none), continuing the session resume ("" for a new one).
func (e *env) runOn(runID, resume string, mc *protocol.RunModelChoice) protocol.RunFinished {
	e.t.Helper()
	e.startRunWith(runID, "MEG-1", func(rs *protocol.RunStart) {
		rs.Prompt, rs.ResumePrompt, rs.ResumeSessionID, rs.ModelChoice = "full prompt", "continue please", resume, mc
	})
	rf := e.finished(runID)
	if rf.Outcome != "completed" || rf.SessionID == nil {
		e.t.Fatalf("finished = %+v", rf)
	}
	return rf
}

func stageEnv(t *testing.T) *env {
	t.Setenv("FAKEAGENT_MODELS", fakeModels)
	t.Setenv("FAKEAGENT_EFFORTS", fakeEfforts)
	t.Setenv("FAKEAGENT_SESSIONS_DIR", t.TempDir())
	t.Setenv("FAKEAGENT_RESUME", "1")
	return newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
}

func TestAModelChoiceReplacesTheAgentsForTheRun(t *testing.T) {
	e := stageEnv(t)
	e.welcomeModel("opus", "high")
	e.runOn("run-1", "", &protocol.RunModelChoice{Model: "sonnet", Effort: "low"})
	if r := e.readReport(); r.PromptModel != "sonnet" || r.PromptEffort != "low" {
		t.Fatalf("prompted on %q / %q", r.PromptModel, r.PromptEffort)
	}
}

func TestAModelWithoutAnEffortRunsOnItsDefaultEffort(t *testing.T) {
	e := stageEnv(t)
	first := e.runOn("run-1", "", nil)
	// the program keeps a resumed session's model and effort: this one was left on opus at max
	t.Setenv("FAKEAGENT_RESUME_MODEL", "opus")
	t.Setenv("FAKEAGENT_RESUME_EFFORT", "max")
	e.runOn("run-2", *first.SessionID, &protocol.RunModelChoice{Model: "opus"})
	if r := e.readReport(); r.PromptModel != "opus" || r.PromptEffort != "default" {
		t.Fatalf("prompted on %q / %q", r.PromptModel, r.PromptEffort)
	}
}

func TestAnExplicitChoiceOnAResumedSessionGoesBackToTheStartingModel(t *testing.T) {
	e := stageEnv(t)
	first := e.runOn("run-1", "", nil)         // a new session: the program's starting model is learned
	t.Setenv("FAKEAGENT_RESUME_MODEL", "opus") // an earlier stage left the session on opus
	t.Setenv("FAKEAGENT_RESUME_EFFORT", "max")
	e.runOn("run-2", *first.SessionID, &protocol.RunModelChoice{})
	r := e.finalReport()
	if last := r.SessionEvents[len(r.SessionEvents)-1]; last != "resume:"+*first.SessionID {
		t.Fatalf("events = %v", r.SessionEvents)
	}
	if rep := e.readReport(); rep.PromptModel != "default" || rep.PromptEffort != "default" {
		t.Fatalf("prompted on %q / %q", rep.PromptModel, rep.PromptEffort)
	}
}

func TestUnknownStartingModelOpensAFreshSessionWithTheResumePrompt(t *testing.T) {
	e := stageEnv(t)
	e.runOn("run-1", "fake-session-1", &protocol.RunModelChoice{})
	r := e.finalReport()
	if len(r.SessionEvents) != 1 || !strings.HasPrefix(r.SessionEvents[0], "new:") {
		t.Fatalf("events = %v", r.SessionEvents)
	}
	if len(r.Prompts) != 1 || r.Prompts[0] != "full prompt\n\ncontinue please" {
		t.Fatalf("prompts = %q", r.Prompts)
	}
	log := e.runLog("run-1")
	if !strings.Contains(log, "runner: fresh_session: ") || strings.Contains(log, "resume_fallback") {
		t.Fatalf("log = %q", log)
	}
}

func TestTheStartingModelIsKeptInTheCache(t *testing.T) {
	e := stageEnv(t)
	e.runOn("run-1", "", nil)
	b, err := os.ReadFile(filepath.Join(e.cache, "model-starts.json"))
	if err != nil || strings.TrimSpace(string(b)) != `{"claude_code":"default"}` {
		t.Fatalf("model-starts.json = %q, %v", b, err)
	}
	// a restarted runner reads it back
	if got, ok := loadStarts(filepath.Join(e.cache, "model-starts.json")).get("claude_code"); !ok || got != "default" {
		t.Fatalf("loaded %q, %v", got, ok)
	}
	if _, ok := loadStarts(filepath.Join(t.TempDir(), "none.json")).get("claude_code"); ok {
		t.Fatal("no file, yet a starting model")
	}
}

func TestWithoutAModelChoiceAResumedSessionKeepsItsModel(t *testing.T) {
	e := stageEnv(t)
	first := e.runOn("run-1", "", nil)
	t.Setenv("FAKEAGENT_RESUME_MODEL", "opus")
	e.runOn("run-2", *first.SessionID, nil)
	if r := e.readReport(); r.PromptModel != "opus" {
		t.Fatalf("prompted on %q", r.PromptModel)
	}
}

func TestAProgramWithoutAModelChoiceStillContinuesItsSessions(t *testing.T) {
	// no FAKEAGENT_MODELS: the agent offers no model list, so there is nothing to go back to
	t.Setenv("FAKEAGENT_SESSIONS_DIR", t.TempDir())
	t.Setenv("FAKEAGENT_RESUME", "1")
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	first := e.runOn("run-1", "", nil)
	e.runOn("run-2", *first.SessionID, &protocol.RunModelChoice{})
	r := e.finalReport()
	if last := r.SessionEvents[len(r.SessionEvents)-1]; last != "resume:"+*first.SessionID {
		t.Fatalf("events = %v", r.SessionEvents)
	}
}
