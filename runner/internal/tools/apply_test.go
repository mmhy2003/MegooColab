package tools

import (
	"encoding/base64"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

func statusOf(results []protocol.ToolResult, program, name string) string {
	for _, r := range results {
		if r.Program == program && r.Name == name {
			return r.Status
		}
	}
	return ""
}

func manifest(t *testing.T) *Manifest {
	t.Helper()
	m, err := LoadManifest()
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func TestApplyInstallsAndRecords(t *testing.T) {
	home := isolate(t)
	m := manifest(t)
	skill := Tool{ToolID: "t2", Name: "ui", Kind: "skill", Rev: 4, Files: []protocol.SkillFile{
		{Path: "SKILL.md", ContentB64: base64.StdEncoding.EncodeToString([]byte("x"))}}}
	tool := httpTool("ctx", "k")
	tool.ReadOnlySafe = true
	results := Apply(home, m, []string{"claude_code", "codex"}, []Tool{tool, skill}, nil)
	for _, p := range []string{"claude_code", "codex"} {
		for _, n := range []string{"ctx", "ui"} {
			if s := statusOf(results, p, n); s != protocol.ToolInstalled {
				t.Fatalf("%s/%s = %q (%+v)", p, n, s, results)
			}
		}
	}
	again := manifest(t)
	e := again.Find("codex", "mcp", "ctx")
	if e == nil || e.ToolID != "t-ctx" || !e.ReadOnlySafe || e.Fingerprint == "" {
		t.Fatalf("manifest entry = %+v", e)
	}
	if s := again.Find("claude_code", "skill", "ui"); s == nil || s.Rev != 4 {
		t.Fatalf("skill entry = %+v", s)
	}
	for _, r := range results {
		if r.Status == protocol.ToolInstalled && (r.ToolID == "" || r.Rev == 0 && r.Name == "ui") {
			t.Fatalf("result without tool id or rev: %+v", r)
		}
	}
}

func TestApplyConflictThenTakeOver(t *testing.T) {
	home := isolate(t)
	os.WriteFile(filepath.Join(home, ".claude.json"), []byte(`{"mcpServers":{"ctx":{"type":"stdio","command":"mine"}}}`), 0o600)
	m := manifest(t)
	results := Apply(home, m, []string{"claude_code"}, []Tool{httpTool("ctx", "k")}, nil)
	if s := statusOf(results, "claude_code", "ctx"); s != protocol.ToolConflict {
		t.Fatalf("status = %q", s)
	}
	if fp, _, _ := claude(t).MCPFingerprint(home, "ctx"); fp != fingerprintJSON(map[string]any{"type": "stdio", "command": "mine"}) {
		t.Fatal("the hand-made entry was touched")
	}
	results = Apply(home, m, []string{"claude_code"}, []Tool{httpTool("ctx", "k")}, []string{"ctx"})
	if s := statusOf(results, "claude_code", "ctx"); s != protocol.ToolInstalled {
		t.Fatalf("take over = %q", s)
	}
	if manifest(t).Find("claude_code", "mcp", "ctx") == nil {
		t.Fatal("taken over entry not recorded")
	}
}

func TestApplyRemovesUnwanted(t *testing.T) {
	home := isolate(t)
	m := manifest(t)
	Apply(home, m, []string{"claude_code"}, []Tool{httpTool("ctx", "k"), httpTool("two", "k")}, nil)
	results := Apply(home, m, []string{"claude_code"}, []Tool{httpTool("two", "k")}, nil)
	if s := statusOf(results, "claude_code", "ctx"); s != protocol.ToolRemoved {
		t.Fatalf("ctx = %q", s)
	}
	if _, exists, _ := claude(t).MCPFingerprint(home, "ctx"); exists {
		t.Fatal("ctx still installed")
	}
	if manifest(t).Find("claude_code", "mcp", "ctx") != nil || manifest(t).Find("claude_code", "mcp", "two") == nil {
		t.Fatalf("manifest = %+v", manifest(t).Entries)
	}
}

func TestApplyOnlyListedPrograms(t *testing.T) {
	home := isolate(t)
	Apply(home, manifest(t), []string{"claude_code"}, []Tool{httpTool("ctx", "k")}, nil)
	if _, err := os.Stat(filepath.Join(home, ".codex", "config.toml")); !os.IsNotExist(err) {
		t.Fatal("codex config written for a program not listed")
	}
}

func TestApplyUnknownProgramNotSupported(t *testing.T) {
	home := isolate(t)
	results := Apply(home, manifest(t), []string{"omp"}, []Tool{httpTool("ctx", "k")}, nil)
	if s := statusOf(results, "omp", "ctx"); s != protocol.ToolNotSupported {
		t.Fatalf("status = %q", s)
	}
}

func TestApplyFailureNeverHoldsValues(t *testing.T) {
	home := isolate(t)
	os.WriteFile(filepath.Join(home, ".claude.json"), []byte(`{"mcpServers": {"x": "sk-live-secret-value"`), 0o600)
	results := Apply(home, manifest(t), []string{"claude_code"}, []Tool{httpTool("ctx", "very-secret-key")}, nil)
	r := results[0]
	if r.Status != protocol.ToolFailed || r.Detail == "" {
		t.Fatalf("result = %+v", r)
	}
	for _, v := range []string{"sk-live-secret-value", "very-secret-key"} {
		if strings.Contains(r.Detail, v) {
			t.Fatalf("detail holds a value: %q", r.Detail)
		}
	}
}

func TestDriftAfterHandEdit(t *testing.T) {
	home := isolate(t)
	m := manifest(t)
	Apply(home, m, []string{"claude_code", "codex"}, []Tool{httpTool("ctx", "k")}, nil)
	if d := Drift(home, m); len(d) != 0 {
		t.Fatalf("fresh drift = %+v", d)
	}
	os.WriteFile(filepath.Join(home, ".claude.json"), []byte(`{"mcpServers":{"ctx":{"type":"http","url":"https://changed"}}}`), 0o600)
	os.Remove(filepath.Join(home, ".codex", "config.toml"))
	d := Drift(home, m)
	got := map[string]string{}
	for _, item := range d {
		got[item.Program+"/"+item.Name] = item.Status
	}
	if got["claude_code/ctx"] != protocol.DriftChanged || got["codex/ctx"] != protocol.DriftMissing || len(d) != 2 {
		t.Fatalf("drift = %+v", d)
	}
}

func TestScanExcludesManaged(t *testing.T) {
	home := isolate(t)
	os.WriteFile(filepath.Join(home, ".claude.json"), []byte(`{"mcpServers":{"mine":{"type":"stdio","command":"foo"}}}`), 0o600)
	m := manifest(t)
	Apply(home, m, []string{"claude_code"}, []Tool{httpTool("ctx", "k")}, nil)
	found := Scan(home, m)
	if len(found) != 1 || found[0].Name != "mine" || found[0].Program != "claude_code" {
		t.Fatalf("found = %+v", found)
	}
}
