// Package adapters knows how to launch the Claude Code and Codex ACP adapters
// and how to start their sessions with the policy applied.
package adapters

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"

	"github.com/mmhy2003/megoocolab/runner/internal/policy"
)

const (
	ClaudeCode = "claude_code"
	Codex      = "codex"
)

// Spec is how to start an adapter process.
type Spec struct {
	Program string
	Command string
	Args    []string
	Env     []string
}

// For returns the launch spec for a program. The environment variable
// MEGOO_ADAPTER_<PROGRAM> (a full command line) replaces the npx command; tests
// and the end-to-end run use it to start a fake agent.
func For(program string) (Spec, error) {
	return forOS(runtime.GOOS, program, os.Getenv, exec.LookPath)
}

func forOS(goos, program string, getenv func(string) string, lookPath func(string) (string, error)) (Spec, error) {
	var pkg string
	switch program {
	case ClaudeCode:
		pkg = "@agentclientprotocol/claude-agent-acp@0.94.0"
	case Codex:
		pkg = "@agentclientprotocol/codex-acp@2.3.0" // replaces the deprecated @zed-industries/codex-acp
	default:
		return Spec{}, fmt.Errorf("adapters: unknown program %q", program)
	}
	if line := getenv("MEGOO_ADAPTER_" + strings.ToUpper(program)); line != "" {
		words, err := splitCommandLine(line)
		if err != nil {
			return Spec{}, fmt.Errorf("adapters: MEGOO_ADAPTER_%s: %w", strings.ToUpper(program), err)
		}
		if len(words) == 0 {
			return Spec{}, fmt.Errorf("adapters: MEGOO_ADAPTER_%s is empty", strings.ToUpper(program))
		}
		return Spec{Program: program, Command: words[0], Args: words[1:]}, nil
	}
	npx := "npx"
	if goos == "windows" {
		npx = "npx.cmd"
		// Some Node installs on Windows (nvm-style) ship npx.exe and no npx.cmd.
		if _, err := lookPath(npx); err != nil {
			npx = "npx"
		}
	}
	return Spec{Program: program, Command: npx, Args: []string{"-y", pkg}}, nil
}

// splitCommandLine splits on whitespace; double quotes group a segment (so
// Windows paths with spaces work) and are removed. No escapes are interpreted.
func splitCommandLine(s string) ([]string, error) {
	var words []string
	var cur strings.Builder
	inWord, inQuote := false, false
	for _, r := range s {
		switch {
		case r == '"':
			inQuote, inWord = !inQuote, true
		case !inQuote && (r == ' ' || r == '\t'):
			if inWord {
				words = append(words, cur.String())
				cur.Reset()
				inWord = false
			}
		default:
			cur.WriteRune(r)
			inWord = true
		}
	}
	if inQuote {
		return nil, fmt.Errorf("unterminated quote")
	}
	if inWord {
		words = append(words, cur.String())
	}
	return words, nil
}

// McpServerName is how MegooColab's MCP server is named inside the agent.
const McpServerName = "megoocolab"

// SessionMeta is the _meta sent with session/new. For Claude Code it cuts off
// the developer's own settings, pre-approves MegooColab's own MCP tools and,
// read-only, removes the edit tools.
func SessionMeta(program string, p policy.Kind) map[string]any {
	if program != ClaudeCode {
		return nil
	}
	opts := map[string]any{
		"settingSources":                  []string{},
		"allowDangerouslySkipPermissions": false,
		// MegooColab's own tools (submit_design, submit_answer, ask_human, ...): without this, plan mode asks and
		// the read-only policy declines every tool of kind "other". The server scopes each call by the run token.
		"allowedTools": []string{"mcp__" + McpServerName},
	}
	if p == policy.ReadOnly {
		opts["disallowedTools"] = []string{"Edit", "Write", "MultiEdit", "NotebookEdit"}
	}
	return map[string]any{"claudeCode": map[string]any{"options": opts}}
}

// ModeFor picks the session mode to set, or "" when none should be set (the
// wanted mode is not among the modes the adapter advertised).
func ModeFor(program string, p policy.Kind, available []string) string {
	want := ""
	switch program {
	case Codex:
		want = map[policy.Kind]string{policy.ReadOnly: "read-only", policy.Workspace: "workspace-write"}[p]
	case ClaudeCode:
		// never "plan": it blocks MegooColab's MCP tools (submit_design, submit_answer, ...). Read-only is enforced
		// by the runner's permission policy, the removed edit tools (SessionMeta) and the R1 repository check.
		want = "default"
	}
	for _, m := range available {
		if m == want {
			return want
		}
	}
	return ""
}
