package jobs

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"

	"github.com/coder/acp-go-sdk"
)

// configSelector is the session's selector of a category, or nil when the
// agent offers no such choice.
func configSelector(opts []acp.SessionConfigOption, category acp.SessionConfigOptionCategory) *acp.SessionConfigOptionSelect {
	for _, o := range opts {
		if o.Select != nil && o.Select.Category != nil && *o.Select.Category == category {
			return o.Select
		}
	}
	return nil
}

func modelSelector(opts []acp.SessionConfigOption) *acp.SessionConfigOptionSelect {
	return configSelector(opts, acp.SessionConfigOptionCategoryModel)
}

func effortSelector(opts []acp.SessionConfigOption) *acp.SessionConfigOptionSelect {
	return configSelector(opts, acp.SessionConfigOptionCategoryThoughtLevel)
}

// option is a model or an effort level the agent offers, as reported to the
// server.
type option struct {
	Value string `json:"value"`
	Name  string `json:"name"`
}

// selectChoices lists the selector's values, groups flattened in order.
func selectChoices(sel *acp.SessionConfigOptionSelect) []option {
	var flat []acp.SessionConfigSelectOption
	if u := sel.Options.Ungrouped; u != nil {
		flat = *u
	}
	if g := sel.Options.Grouped; g != nil {
		for _, group := range *g {
			flat = append(flat, group.Options...)
		}
	}
	out := make([]option, 0, len(flat))
	for _, o := range flat {
		out = append(out, option{Value: string(o.Value), Name: o.Name})
	}
	return out
}

// modelKey is a name as an id: "GPT-6.1 Sol" and "gpt-6.1-sol" are the same
// model.
func modelKey(s string) string {
	return strings.Join(strings.Fields(strings.ToLower(s)), "-")
}

// resolve is the offered value the owner meant: the value, or its name (case
// and spaces aside). "" when none matches: the agent may still resolve an
// alias.
func resolve(choices []option, want string) string {
	key := modelKey(want)
	for _, c := range choices {
		if c.Value == want || modelKey(c.Value) == key || modelKey(c.Name) == key {
			return c.Value
		}
	}
	return ""
}

func listed(choices []option, value string) bool {
	for _, c := range choices {
		if c.Value == value {
			return true
		}
	}
	return false
}

func nameOf(choices []option, value string) string {
	for _, c := range choices {
		if c.Value == value {
			return c.Name
		}
	}
	return value
}

// efforts are each program's models' effort levels. Reading them means
// switching a session through every model (seconds for a dozen models), so a
// runner learns them on a program's first run and keeps them: the adapter, and
// so its models, only change with the runner.
type efforts struct {
	mu        sync.Mutex
	byProgram map[string]map[string][]option // program -> model value -> levels (none: no effort setting)
}

// levels are the efforts of every model offered, learning the ones not known
// yet by switching the session to each; moved says it did, and the session is
// then on another model than it started on.
func (e *efforts) levels(ctx context.Context, ac *acp.ClientSideConnection, sid acp.SessionId, program string,
	sel *acp.SessionConfigOptionSelect, models []option) (_ map[string][]option, moved bool, _ error) {
	e.mu.Lock()
	known := e.byProgram[program]
	var missing []option
	for _, m := range models {
		if _, ok := known[m.Value]; !ok {
			missing = append(missing, m)
		}
	}
	e.mu.Unlock()
	learned := map[string][]option{}
	for _, m := range missing {
		resp, err := setOption(ctx, ac, sid, sel.Id, m.Value)
		if err != nil {
			if ctx.Err() != nil {
				return nil, moved, ctx.Err()
			}
			continue // a model the agent will not switch to: its levels stay unknown
		}
		moved = true
		learned[m.Value] = []option{}
		if es := effortSelector(resp.ConfigOptions); es != nil {
			learned[m.Value] = selectChoices(es)
		}
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.byProgram == nil {
		e.byProgram = map[string]map[string][]option{}
	}
	if e.byProgram[program] == nil {
		e.byProgram[program] = map[string][]option{}
	}
	out := map[string][]option{}
	for v, l := range learned {
		e.byProgram[program][v] = l
	}
	for v, l := range e.byProgram[program] {
		out[v] = l
	}
	return out, moved, nil
}

func setOption(ctx context.Context, ac *acp.ClientSideConnection, sid acp.SessionId, id acp.SessionConfigId,
	value string) (acp.SetSessionConfigOptionResponse, error) {
	return ac.SetSessionConfigOption(ctx, acp.SetSessionConfigOptionRequest{ValueId: &acp.SetSessionConfigOptionValueId{
		ConfigId: id, SessionId: sid, Value: acp.SessionConfigValueId(value),
	}})
}

// choice is what a session starts on: the agent's chosen model and effort ("":
// its defaults).
type choice struct {
	model, effort, program string
	efforts                *efforts
}

// startModel reports the models the agent offers with their effort levels,
// puts the session on the chosen model and effort, and reports what the run
// uses. An error, with its failure code, means the choice could not be made, or
// the agent took a model without listing it (Codex takes any name as a model
// of its own, which fails only once the run talks to it): the run must not go
// on.
func startModel(ctx context.Context, ac *acp.ClientSideConnection, sess openedSession, want choice,
	emit func(string, map[string]any)) (string, error) {
	wantModel, wantEffort := strings.TrimSpace(want.model), strings.TrimSpace(want.effort)
	sel := modelSelector(sess.options)
	if sel == nil {
		if wantModel != "" {
			return "model_unavailable", errors.New("the agent offers no model choice")
		}
		if wantEffort != "" {
			return "effort_unavailable", errors.New("the agent offers no model choice")
		}
		return "", nil
	}
	models := selectChoices(sel)
	levels, moved, err := want.efforts.levels(ctx, ac, sess.id, want.program, sel, models)
	if err != nil {
		return "model_unavailable", err
	}
	options := make([]any, len(models))
	for i, m := range models {
		efforts := make([]any, 0, len(levels[m.Value]))
		for _, l := range levels[m.Value] {
			efforts = append(efforts, map[string]any{"value": l.Value, "name": l.Name})
		}
		options[i] = map[string]any{"value": m.Value, "name": m.Name, "efforts": efforts}
	}
	emit("model_options", map[string]any{"options": options})

	start := string(sel.CurrentValue)
	current, latest := start, sess.options
	if wantModel != "" {
		if current = resolve(models, wantModel); current == "" {
			current = wantModel
		}
	}
	// learning the levels moved the session through the models: it goes back to the one it runs on
	if moved || current != start {
		resp, err := setOption(ctx, ac, sess.id, sel.Id, current)
		if err != nil {
			return "model_unavailable", fmt.Errorf("set model %q: %w", current, err)
		}
		if resp.ConfigOptions != nil {
			latest = resp.ConfigOptions // an agent that answers without its options keeps the session's
		}
		if after := modelSelector(resp.ConfigOptions); after != nil {
			current = string(after.CurrentValue)
		}
		if !listed(models, current) {
			return "model_unavailable", fmt.Errorf("the agent does not list model %q", wantModel)
		}
	}
	used := map[string]any{"value": current, "name": nameOf(models, current)}

	es := effortSelector(latest)
	if es == nil {
		if wantEffort != "" {
			return "effort_unavailable", fmt.Errorf("model %q has no effort setting", current)
		}
		emit("model", used)
		return "", nil
	}
	effortLevels := selectChoices(es)
	effort := string(es.CurrentValue)
	if wantEffort != "" {
		value := resolve(effortLevels, wantEffort)
		if value == "" {
			return "effort_unavailable", fmt.Errorf("model %q has no %q effort", current, wantEffort)
		}
		if value != effort {
			resp, err := setOption(ctx, ac, sess.id, es.Id, value)
			if err != nil {
				return "effort_unavailable", fmt.Errorf("set effort %q: %w", value, err)
			}
			effort = value
			if after := effortSelector(resp.ConfigOptions); after != nil {
				effort = string(after.CurrentValue)
			}
		}
	}
	used["effort"], used["effort_name"] = effort, nameOf(effortLevels, effort)
	emit("model", used)
	return "", nil
}
