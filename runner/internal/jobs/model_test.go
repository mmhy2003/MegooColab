package jobs

import (
	"testing"

	"github.com/coder/acp-go-sdk"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

const (
	fakeModels = "default=Default (recommended),opus=Opus 4.7,sonnet=Sonnet 4.6"
	// opus and sonnet have effort levels, the default model has none
	fakeEfforts = "opus=low|high|max;sonnet=low|high"
)

// welcomeModel re-sends the welcome with the agent's chosen model and effort.
func (e *env) welcomeModel(model string, effort ...string) {
	e.t.Helper()
	a := protocol.WelcomeAgent{
		AgentID: "agent-1", Name: "A", Program: "claude_code", MaxConcurrentRuns: 1, Model: model,
		Bindings: []protocol.WelcomeBinding{{ProjectKey: "MEG", LocalPath: e.repo}},
	}
	if len(effort) > 0 {
		a.Effort = effort[0]
	}
	if err := e.srv.Send(protocol.Welcome{Type: protocol.TypeWelcome, UserID: "u1", Agents: []protocol.WelcomeAgent{a}}); err != nil {
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

func (e *env) failsWith(runID, code string) {
	e.t.Helper()
	if rf := e.finished(runID); rf.Outcome != "failed" || rf.Error == nil || *rf.Error != code {
		e.t.Fatalf("finished = %+v", rf)
	}
	if got := e.readReport().Prompts; len(got) != 0 {
		e.t.Fatalf("the agent was prompted: %v", got)
	}
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
	if len(opts) != 1 || jsonStr(opts[0].Data["options"]) != `[{"efforts":[],"name":"Default (recommended)","value":"default"},`+
		`{"efforts":[],"name":"Opus 4.7","value":"opus"},{"efforts":[],"name":"Sonnet 4.6","value":"sonnet"}]` {
		t.Fatalf("model_options = %+v", opts)
	}
	used := updatesOf(ups, "model")
	if len(used) != 1 || jsonStr(used[0].Data) != `{"name":"Default (recommended)","value":"default"}` {
		t.Fatalf("model = %+v", used)
	}
	if r := e.readReport(); r.PromptModel != "default" {
		t.Fatalf("no model was chosen, yet the prompt went to %q", r.PromptModel)
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
			if r := e.readReport(); r.PromptModel != "opus" {
				t.Fatalf("prompted on %q", r.PromptModel)
			}
		})
	}
}

func TestRunOnAModelTheAgentDoesNotOfferFailsBeforeThePrompt(t *testing.T) {
	t.Setenv("FAKEAGENT_MODELS", fakeModels)
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.welcomeModel("gpt-9")
	e.startRun("run-1", "MEG-1", "read_only")
	e.failsWith("run-1", "model_unavailable")
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
	e.failsWith("run-1", "model_unavailable")
}

func TestRunWithAModelOnAnAgentOfferingNoChoiceFails(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.welcomeModel("opus")
	e.startRun("run-1", "MEG-1", "read_only")
	e.failsWith("run-1", "model_unavailable")
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

func TestRunReportsEachModelsEffortLevelsAndStartsOnTheChosenOne(t *testing.T) {
	t.Setenv("FAKEAGENT_MODELS", fakeModels)
	t.Setenv("FAKEAGENT_EFFORTS", fakeEfforts)
	for _, chosen := range []string{"high", "High"} {
		t.Run(chosen, func(t *testing.T) {
			e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
			e.welcomeModel("opus", chosen)
			e.startRun("run-1", "MEG-1", "read_only")
			if rf := e.finished("run-1"); rf.Outcome != "completed" {
				t.Fatalf("finished = %+v", rf)
			}
			ups := e.updates("run-1")
			opts := updatesOf(ups, "model_options")
			levels := `[{"name":"Default","value":"default"},{"name":"Low","value":"low"},{"name":"High","value":"high"}`
			if len(opts) != 1 || jsonStr(opts[0].Data["options"]) != `[{"efforts":[],"name":"Default (recommended)","value":"default"},`+
				`{"efforts":`+levels+`,{"name":"Max","value":"max"}],"name":"Opus 4.7","value":"opus"},`+
				`{"efforts":`+levels+`],"name":"Sonnet 4.6","value":"sonnet"}]` {
				t.Fatalf("model_options = %s", jsonStr(opts))
			}
			used := updatesOf(ups, "model")
			if len(used) != 1 || jsonStr(used[0].Data) != `{"effort":"high","effort_name":"High","name":"Opus 4.7","value":"opus"}` {
				t.Fatalf("model = %s", jsonStr(used))
			}
			if r := e.readReport(); r.PromptModel != "opus" || r.PromptEffort != "high" {
				t.Fatalf("prompted on %q with %q effort", r.PromptModel, r.PromptEffort)
			}
		})
	}
}

func TestRunWithoutAnEffortLeavesTheModelsOwn(t *testing.T) {
	t.Setenv("FAKEAGENT_MODELS", fakeModels)
	t.Setenv("FAKEAGENT_EFFORTS", fakeEfforts)
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.welcomeModel("opus")
	e.startRun("run-1", "MEG-1", "read_only")
	e.finished("run-1")
	used := updatesOf(e.updates("run-1"), "model")
	if len(used) != 1 || used[0].Data["effort"] != "default" || used[0].Data["effort_name"] != "Default" {
		t.Fatalf("model = %s", jsonStr(used))
	}
	if r := e.readReport(); len(r.EffortsSet) != 0 {
		t.Fatalf("efforts set = %v", r.EffortsSet)
	}
}

func TestRunOnAnEffortTheModelDoesNotOfferFailsBeforeThePrompt(t *testing.T) {
	t.Setenv("FAKEAGENT_MODELS", fakeModels)
	t.Setenv("FAKEAGENT_EFFORTS", fakeEfforts)
	for _, c := range []struct{ model, effort string }{
		{"sonnet", "max"},  // sonnet has no max
		{"default", "low"}, // the default model has no effort setting
	} {
		t.Run(c.model, func(t *testing.T) {
			e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
			e.welcomeModel(c.model, c.effort)
			e.startRun("run-1", "MEG-1", "read_only")
			e.failsWith("run-1", "effort_unavailable")
			if len(updatesOf(e.updates("run-1"), "model_options")) != 1 {
				t.Fatal("the models offered were not reported")
			}
		})
	}
}

func TestEffortLevelsAreLearnedOncePerProgram(t *testing.T) {
	t.Setenv("FAKEAGENT_MODELS", fakeModels)
	t.Setenv("FAKEAGENT_EFFORTS", fakeEfforts)
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.startRun("run-1", "MEG-1", "read_only")
	e.finished("run-1")
	if r := e.readReport(); len(r.ModelsSet) == 0 {
		t.Fatal("the first run did not go through the models")
	}
	e.startRun("run-2", "MEG-2", "read_only")
	e.finished("run-2")
	if r := e.readReport(); len(r.ModelsSet) != 0 {
		t.Fatalf("the second run went through the models again: %v", r.ModelsSet)
	}
	first := updatesOf(e.updates("run-1"), "model_options")[0].Data["options"]
	if opts := updatesOf(e.updates("run-2"), "model_options"); len(opts) != 1 || jsonStr(opts[0].Data["options"]) != jsonStr(first) {
		t.Fatalf("the second run reported other levels: %s", jsonStr(opts))
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
	if got := jsonStr(selectChoices(sel)); got != `[{"value":"opus","name":"Opus"},{"value":"haiku","name":"Haiku"}]` {
		t.Fatalf("choices = %s", got)
	}
}
