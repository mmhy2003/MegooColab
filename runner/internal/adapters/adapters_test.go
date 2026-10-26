package adapters

import (
	"os/exec"
	"reflect"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/policy"
)

func noEnv(string) string { return "" }

func TestClaudeReadOnlyMetaDisallowsEdits(t *testing.T) {
	m := SessionMeta("claude_code", policy.ReadOnly)
	opts := m["claudeCode"].(map[string]any)["options"].(map[string]any)
	if got := opts["disallowedTools"]; !reflect.DeepEqual(got, []string{"Edit", "Write", "MultiEdit", "NotebookEdit"}) {
		t.Fatalf("disallowedTools = %#v", got)
	}
	if got := opts["settingSources"]; !reflect.DeepEqual(got, []string{}) {
		t.Fatalf("settingSources = %#v", got)
	}
	if opts["allowDangerouslySkipPermissions"] != false {
		t.Fatalf("allowDangerouslySkipPermissions = %#v", opts["allowDangerouslySkipPermissions"])
	}
	w := SessionMeta("claude_code", policy.Workspace)["claudeCode"].(map[string]any)["options"].(map[string]any)
	if _, ok := w["disallowedTools"]; ok {
		t.Fatal("workspace must not set disallowedTools")
	}
	// MegooColab's own MCP server is pre-approved in both policies: Claude's plan mode (read-only) would
	// otherwise ask, and the read-only policy declines tools of kind "other", so submit_design,
	// submit_answer, ask_human and submit_review could never be called by a real agent
	for _, o := range []map[string]any{opts, w} {
		if got := o["allowedTools"]; !reflect.DeepEqual(got, []string{"mcp__megoocolab"}) {
			t.Fatalf("allowedTools = %#v", got)
		}
	}
	if SessionMeta("codex", policy.ReadOnly) != nil {
		t.Fatal("codex meta must be nil")
	}
}

func TestModeFor(t *testing.T) {
	cases := []struct {
		program   string
		kind      policy.Kind
		available []string
		want      string
	}{
		{"codex", policy.ReadOnly, []string{"read-only", "auto", "full-access"}, "read-only"},
		{"codex", policy.Workspace, []string{"read-only", "auto", "full-access"}, "auto"},
		// not plan mode: it blocks MegooColab's MCP tools (submit_design, submit_answer, ...); read-only is enforced by
		// the runner's permission policy, the removed edit tools and the R1 repository check
		{"claude_code", policy.ReadOnly, []string{"default", "plan"}, "default"},
		{"claude_code", policy.ReadOnly, []string{"plan"}, ""},
		{"claude_code", policy.Workspace, []string{"default", "plan"}, "default"},
		{"codex", policy.ReadOnly, []string{"auto"}, ""},
		{"nope", policy.ReadOnly, []string{"plan"}, ""},
	}
	for _, c := range cases {
		if got := ModeFor(c.program, c.kind, c.available); got != c.want {
			t.Errorf("ModeFor(%s,%s,%v) = %q, want %q", c.program, c.kind, c.available, got, c.want)
		}
	}
}

func TestDefaultSpecs(t *testing.T) {
	s, err := forOS("linux", "claude_code", noEnv, lookAll)
	if err != nil {
		t.Fatal(err)
	}
	if s.Command != "npx" || !reflect.DeepEqual(s.Args, []string{"-y", "@agentclientprotocol/claude-agent-acp@0.94.0"}) {
		t.Fatalf("claude spec = %+v", s)
	}
	s, _ = forOS("linux", "codex", noEnv, lookAll)
	if s.Command != "npx" || !reflect.DeepEqual(s.Args, []string{"-y", "@zed-industries/codex-acp@0.16.0"}) {
		t.Fatalf("codex spec = %+v", s)
	}
	if _, err := forOS("linux", "other", noEnv, lookAll); err == nil {
		t.Fatal("unknown program must fail")
	}
}

func TestWindowsUsesNpxCmd(t *testing.T) {
	s, err := forOS("windows", "codex", noEnv, lookAll)
	if err != nil {
		t.Fatal(err)
	}
	if s.Command != "npx.cmd" {
		t.Fatalf("command = %q", s.Command)
	}
}

func TestOverrideEnv(t *testing.T) {
	env := func(k string) string {
		switch k {
		case "MEGOO_ADAPTER_CLAUDE_CODE":
			return `"C:\Program Files\fake agent.exe" --scenario  "a b" plain`
		case "MEGOO_ADAPTER_CODEX":
			return "/bin/fake"
		}
		return ""
	}
	s, err := forOS("windows", "claude_code", env, lookAll)
	if err != nil {
		t.Fatal(err)
	}
	if s.Command != `C:\Program Files\fake agent.exe` || !reflect.DeepEqual(s.Args, []string{"--scenario", "a b", "plain"}) {
		t.Fatalf("spec = %+v", s)
	}
	s, _ = forOS("linux", "codex", env, lookAll)
	if s.Command != "/bin/fake" || len(s.Args) != 0 {
		t.Fatalf("spec = %+v", s)
	}
}

func TestOverrideEnvUnterminatedQuote(t *testing.T) {
	env := func(string) string { return `"oops` }
	if _, err := forOS("linux", "codex", env, lookAll); err == nil {
		t.Fatal("expected error")
	}
}

func lookAll(string) (string, error) { return "", nil }

func lookOnly(name string) func(string) (string, error) {
	return func(s string) (string, error) {
		if s == name {
			return s, nil
		}
		return "", exec.ErrNotFound
	}
}

func TestWindowsNpxFallback(t *testing.T) {
	s, err := forOS("windows", "codex", noEnv, lookOnly("npx.cmd"))
	if err != nil || s.Command != "npx.cmd" {
		t.Fatalf("only npx.cmd present: %+v %v", s, err)
	}
	s, err = forOS("windows", "codex", noEnv, lookOnly("npx.exe"))
	if err != nil || s.Command != "npx" {
		t.Fatalf("only npx.exe present: %+v %v", s, err)
	}
}
