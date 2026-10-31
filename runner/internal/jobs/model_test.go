package jobs

import (
	"testing"

	"github.com/coder/acp-go-sdk"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

const fakeModels = "default=Default (recommended),opus=Opus 4.7,sonnet=Sonnet 4.6"

// welcomeModel re-sends the welcome with the agent's chosen model.
func (e *env) welcomeModel(model string) {
	e.t.Helper()
	if err := e.srv.Send(protocol.Welcome{
		Type: protocol.TypeWelcome, UserID: "u1",
		Agents: []protocol.WelcomeAgent{{
			AgentID: "agent-1", Name: "A", Program: "claude_code", MaxConcurrentRuns: 1, Model: model,
			Bindings: []protocol.WelcomeBinding{{ProjectKey: "MEG", LocalPath: e.repo}},
		}},
	}); err != nil {
		e.t.Fatal(err)
	}
}

func updatesOf(ups []protocol.RunUpdate, kind string) []protocol.RunUpdate {
	var out []protocol.RunUpdate
	for _, u := range ups {
		if u.Kind == kind {
			out = append(out, u)
		}
	}
	return out
}

func TestRunReportsTheModelsOfferedAndTheOneItUses(t *testing.T) {
	t.Setenv("FAKEAGENT_MODELS", fakeModels)
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.startRun("run-1", "MEG-1", "read_only")
	if rf := e.finished("run-1"); rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	ups := e.updates("run-1")
	opts := updatesOf(ups, "model_options")
	if len(opts) != 1 || jsonStr(opts[0].Data["options"]) !=
		`[{"name":"Default (recommended)","value":"default"},{"name":"Opus 4.7","value":"opus"},{"name":"Sonnet 4.6","value":"sonnet"}]` {
		t.Fatalf("model_options = %+v", opts)
	}
	used := updatesOf(ups, "model")
	if len(used) != 1 || used[0].Data["value"] != "default" || used[0].Data["name"] != "Default (recommended)" {
		t.Fatalf("model = %+v", used)
	}
	if got := e.readReport().ModelsSet; len(got) != 0 {
		t.Fatalf("no model was chosen, yet the runner set %v", got)
	}
}

func TestRunStartsOnTheChosenModel(t *testing.T) {
	t.Setenv("FAKEAGENT_MODELS", fakeModels)
	// its value, its name in any case, or the name written as an id
	for _, chosen := range []string{"opus", "OPUS 4.7", "opus-4.7"} {
		t.Run(chosen, func(t *testing.T) {
			e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
			e.welcomeModel(chosen)
			e.startRun("run-1", "MEG-1", "read_only")
			if rf := e.finished("run-1"); rf.Outcome != "completed" {
				t.Fatalf("finished = %+v", rf)
			}
			used := updatesOf(e.updates("run-1"), "model")
			if len(used) != 1 || used[0].Data["value"] != "opus" || used[0].Data["name"] != "Opus 4.7" {
				t.Fatalf("model = %+v", used)
			}
			if got := e.readReport().ModelsSet; len(got) != 1 || got[0] != "opus" {
				t.Fatalf("models set = %v", got)
			}
		})
	}
}

func TestRunOnAModelTheAgentDoesNotOfferFailsBeforeThePrompt(t *testing.T) {
	t.Setenv("FAKEAGENT_MODELS", fakeModels)
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.welcomeModel("gpt-9")
	e.startRun("run-1", "MEG-1", "read_only")
	if rf := e.finished("run-1"); rf.Outcome != "failed" || rf.Error == nil || *rf.Error != "model_unavailable" {
		t.Fatalf("finished = %+v", rf)
	}
	ups := e.updates("run-1")
	if len(updatesOf(ups, "model_options")) != 1 {
		t.Fatalf("the models offered were not reported: %+v", ups)
	}
	if len(updatesOf(ups, "model")) != 0 || len(updatesOf(ups, "message")) != 0 {
		t.Fatalf("the run went on: %+v", ups)
	}
}

// Codex takes any name it doesn't know as a model of its own, which would only
// fail once the run talks to the model: a model the agent did not list is not
// used.
func TestRunOnAModelTheAgentTakesButDoesNotListFails(t *testing.T) {
	t.Setenv("FAKEAGENT_MODELS", fakeModels)
	t.Setenv("FAKEAGENT_MODELS_ANY", "1")
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.welcomeModel("gpt-9")
	e.startRun("run-1", "MEG-1", "read_only")
	if rf := e.finished("run-1"); rf.Outcome != "failed" || rf.Error == nil || *rf.Error != "model_unavailable" {
		t.Fatalf("finished = %+v", rf)
	}
	if got := e.readReport().Prompts; len(got) != 0 {
		t.Fatalf("the agent was prompted: %v", got)
	}
}

func TestRunWithAModelOnAnAgentOfferingNoChoiceFails(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.welcomeModel("opus")
	e.startRun("run-1", "MEG-1", "read_only")
	if rf := e.finished("run-1"); rf.Outcome != "failed" || rf.Error == nil || *rf.Error != "model_unavailable" {
		t.Fatalf("finished = %+v", rf)
	}
}

func TestRunWithoutAModelOnAnAgentOfferingNoChoiceReportsNothing(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.startRun("run-1", "MEG-1", "read_only")
	if rf := e.finished("run-1"); rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	ups := e.updates("run-1")
	if len(updatesOf(ups, "model")) != 0 || len(updatesOf(ups, "model_options")) != 0 {
		t.Fatalf("updates = %+v", ups)
	}
}

func TestModelSelectorReadsGroupedOptions(t *testing.T) {
	cat := acp.SessionConfigOptionCategoryModel
	grouped := acp.SessionConfigSelectOptionsGrouped{
		{Group: "a", Name: "Claude", Options: []acp.SessionConfigSelectOption{{Value: "opus", Name: "Opus"}}},
		{Group: "b", Name: "Other", Options: []acp.SessionConfigSelectOption{{Value: "haiku", Name: "Haiku"}}},
	}
	opts := []acp.SessionConfigOption{
		{Select: &acp.SessionConfigOptionSelect{Id: "effort", Name: "Effort", CurrentValue: "high"}},
		{Select: &acp.SessionConfigOptionSelect{Id: "model", Name: "Model", Category: &cat, CurrentValue: "opus",
			Options: acp.SessionConfigSelectOptions{Grouped: &grouped}}},
	}
	sel := modelSelector(opts)
	if sel == nil || sel.Id != "model" {
		t.Fatalf("selector = %+v", sel)
	}
	if got := jsonStr(modelChoices(sel)); got != `[{"value":"opus","name":"Opus"},{"value":"haiku","name":"Haiku"}]` {
		t.Fatalf("choices = %s", got)
	}
}
