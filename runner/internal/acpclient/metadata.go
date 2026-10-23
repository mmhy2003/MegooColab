package acpclient

import (
	"fmt"
	"strings"

	"github.com/coder/acp-go-sdk"
	"github.com/mmhy2003/megoocolab/runner/internal/policy"
)

// This file is the only place that turns ACP data into run-update metadata.
// Every mapping builds a fresh map from an explicit field list, so nothing the
// agent sends (content blocks, diffs, raw input or output) can slip through.
// Limits mirror the server's allow-list (backend app/agent_runs/service.py).
const (
	maxText        = 4000
	maxTitle       = 200
	maxPlanEntries = 50
)

// truncate cuts s to at most n runes.
func truncate(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}

// toolKind maps an ACP tool kind to the server's vocabulary.
func toolKind(k acp.ToolKind) string {
	switch k {
	case acp.ToolKindRead, acp.ToolKindEdit, acp.ToolKindDelete, acp.ToolKindMove, acp.ToolKindSearch,
		acp.ToolKindExecute, acp.ToolKindThink, acp.ToolKindFetch:
		return string(k)
	}
	return "other"
}

func toolStatus(s acp.ToolCallStatus) string {
	switch s {
	case acp.ToolCallStatusPending, acp.ToolCallStatusInProgress, acp.ToolCallStatusCompleted, acp.ToolCallStatusFailed:
		return string(s)
	}
	return ""
}

func planStatus(s acp.PlanEntryStatus) string {
	switch s {
	case acp.PlanEntryStatusPending, acp.PlanEntryStatusInProgress, acp.PlanEntryStatusCompleted:
		return string(s)
	}
	return "pending"
}

// commandOf extracts the command line of an execute tool call from its raw
// input. It is used only for the policy check and to derive the program name;
// it is never sent on.
func commandOf(rawInput any) string {
	m, ok := rawInput.(map[string]any)
	if !ok {
		return ""
	}
	switch v := m["command"].(type) {
	case string:
		return v
	case []any:
		parts := make([]string, 0, len(v))
		for _, p := range v {
			s, ok := p.(string)
			if !ok {
				return ""
			}
			parts = append(parts, s)
		}
		return strings.Join(parts, " ")
	}
	return ""
}

// displayTitle is the title that goes to the server. A command's arguments can
// hold secrets, so an execute tool is titled by its program name alone.
func displayTitle(kind acp.ToolKind, title, command string) string {
	if kind == acp.ToolKindExecute {
		if base := policy.FirstTokenBase(command); base != "" {
			return truncate("Run "+base, maxTitle)
		}
		return "Run command"
	}
	return truncate(title, maxTitle)
}

func planEntries(entries []acp.PlanEntry) []map[string]any {
	if len(entries) > maxPlanEntries {
		entries = entries[:maxPlanEntries]
	}
	out := make([]map[string]any, 0, len(entries))
	for _, e := range entries {
		out = append(out, map[string]any{"title": truncate(e.Content, maxTitle), "status": planStatus(e.Status)})
	}
	return out
}

func toolData(kind acp.ToolKind, title string, status acp.ToolCallStatus) map[string]any {
	d := map[string]any{"tool_kind": toolKind(kind), "title": title}
	if s := toolStatus(status); s != "" {
		d["status"] = s
	}
	return d
}

func permissionData(kind acp.ToolKind, title string, allowed bool, reason string) map[string]any {
	decision := "denied"
	if allowed {
		decision = "allowed"
	}
	return map[string]any{
		"tool_kind": toolKind(kind),
		"title":     truncate(title, maxTitle),
		"decision":  decision,
		"reason":    truncate(reason, maxTitle),
	}
}

func fileChangeData(relPath string, added, removed int) map[string]any {
	return map[string]any{"path": relPath, "lines_added": added, "lines_removed": removed}
}

// splitLines splits on "\n"; a final newline does not start another line.
func splitLines(s string) []string {
	if s == "" {
		return nil
	}
	lines := strings.Split(s, "\n")
	if lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	return lines
}

// lcsCellLimit bounds the diff work; beyond it every changed line counts as
// replaced, which over-counts but never reads or sends content.
const lcsCellLimit = 4_000_000

// lineCounts diffs old and new text by lines and returns only the counts.
func lineCounts(oldText, newText string) (added, removed int) {
	a, b := splitLines(oldText), splitLines(newText)
	for len(a) > 0 && len(b) > 0 && a[0] == b[0] {
		a, b = a[1:], b[1:]
	}
	for len(a) > 0 && len(b) > 0 && a[len(a)-1] == b[len(b)-1] {
		a, b = a[:len(a)-1], b[:len(b)-1]
	}
	if len(a) == 0 || len(b) == 0 || len(a)*len(b) > lcsCellLimit {
		return len(b), len(a)
	}
	prev, cur := make([]int, len(b)+1), make([]int, len(b)+1)
	for i := 1; i <= len(a); i++ {
		for j := 1; j <= len(b); j++ {
			switch {
			case a[i-1] == b[j-1]:
				cur[j] = prev[j-1] + 1
			case prev[j] >= cur[j-1]:
				cur[j] = prev[j]
			default:
				cur[j] = cur[j-1]
			}
		}
		prev, cur = cur, prev
	}
	lcs := prev[len(b)]
	return len(b) - lcs, len(a) - lcs
}

var errNotSupported = fmt.Errorf("terminal methods are not supported by the MegooColab runner")
