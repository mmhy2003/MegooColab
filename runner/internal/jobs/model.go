package jobs

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/coder/acp-go-sdk"
)

// modelSelector is the session's model selector (category "model"), or nil
// when the agent offers no model choice.
func modelSelector(opts []acp.SessionConfigOption) *acp.SessionConfigOptionSelect {
	for _, o := range opts {
		if o.Select != nil && o.Select.Category != nil && *o.Select.Category == acp.SessionConfigOptionCategoryModel {
			return o.Select
		}
	}
	return nil
}

// modelChoice is a model the agent offers, as reported to the server.
type modelChoice struct {
	Value string `json:"value"`
	Name  string `json:"name"`
}

// modelChoices lists the selector's models, groups flattened in order.
func modelChoices(sel *acp.SessionConfigOptionSelect) []modelChoice {
	var flat []acp.SessionConfigSelectOption
	if u := sel.Options.Ungrouped; u != nil {
		flat = *u
	}
	if g := sel.Options.Grouped; g != nil {
		for _, group := range *g {
			flat = append(flat, group.Options...)
		}
	}
	out := make([]modelChoice, 0, len(flat))
	for _, o := range flat {
		out = append(out, modelChoice{Value: string(o.Value), Name: o.Name})
	}
	return out
}

// modelKey is a model name as an id: "GPT-6.1 Sol" and "gpt-6.1-sol" are the
// same model.
func modelKey(s string) string {
	return strings.Join(strings.Fields(strings.ToLower(s)), "-")
}

// resolveModel is the offered model the owner meant: its value, or its name
// (case and spaces aside). "" when none matches: the agent may still resolve
// an alias.
func resolveModel(choices []modelChoice, want string) string {
	key := modelKey(want)
	for _, c := range choices {
		if c.Value == want || modelKey(c.Value) == key || modelKey(c.Name) == key {
			return c.Value
		}
	}
	return ""
}

func listed(choices []modelChoice, value string) bool {
	for _, c := range choices {
		if c.Value == value {
			return true
		}
	}
	return false
}

// startModel reports the models the agent offers, puts the session on the
// agent's chosen model ("" keeps the agent's default) and reports the model
// the run uses. An error means the chosen model could not be set, or the agent
// took it without listing it (Codex takes any name as a model of its own, which
// fails only once the run talks to it): the run must not go on.
func startModel(ctx context.Context, ac *acp.ClientSideConnection, sess openedSession, want string,
	emit func(string, map[string]any)) error {
	want = strings.TrimSpace(want)
	sel := modelSelector(sess.options)
	if sel == nil {
		if want != "" {
			return errors.New("the agent offers no model choice")
		}
		return nil
	}
	choices := modelChoices(sel)
	options := make([]any, len(choices))
	for i, c := range choices {
		options[i] = map[string]any{"value": c.Value, "name": c.Name}
	}
	emit("model_options", map[string]any{"options": options})

	current := string(sel.CurrentValue)
	if want != "" {
		value := resolveModel(choices, want)
		if value == "" {
			value = want
		}
		if value != current {
			resp, err := ac.SetSessionConfigOption(ctx, acp.SetSessionConfigOptionRequest{ValueId: &acp.SetSessionConfigOptionValueId{
				ConfigId: sel.Id, SessionId: sess.id, Value: acp.SessionConfigValueId(value),
			}})
			if err != nil {
				return fmt.Errorf("set model %q: %w", want, err)
			}
			current = value // an agent that answers without its options took the value as sent
			if after := modelSelector(resp.ConfigOptions); after != nil {
				current = string(after.CurrentValue)
			}
			if !listed(choices, current) {
				return fmt.Errorf("the agent does not list model %q", want)
			}
		}
	}
	name := current
	for _, c := range choices {
		if c.Value == current {
			name = c.Name
		}
	}
	emit("model", map[string]any{"value": current, "name": name})
	return nil
}
