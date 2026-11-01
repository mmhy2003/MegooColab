package jobs

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// isolateHome points the home and config folders at a temporary folder, so a push never reaches the real
// ~/.claude.json or ~/.codex.
func isolateHome(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("APPDATA", filepath.Join(home, "config"))
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(home, "config"))
	t.Setenv("CODEX_HOME", "")
	return home
}

func TestToolsPushReportAndDrift(t *testing.T) {
	home := isolateHome(t)
	e := newEnvWithCache(t, "[]", 1, t.TempDir())
	if f := e.srv.WaitFrame(t, protocol.TypeToolsDrift); string(f.Raw) != `{"type":"tools_drift","items":[]}` {
		t.Fatalf("first drift = %s", f.Raw)
	}
	push := protocol.ToolsPush{Type: protocol.TypeToolsPush, PushID: "p1", Programs: []string{"claude_code"}, TakeOver: []string{},
		Tools: []protocol.ToolPayload{{ToolID: "t1", Name: "ctx", Kind: "mcp", Rev: 2,
			Mcp: &protocol.McpPayload{Transport: "http", URL: "https://mcp.example.com/mcp", Headers: map[string]string{"X-Key": "k"},
				Args: []string{}, Env: map[string]string{}}}}}
	if err := e.srv.Send(push); err != nil {
		t.Fatal(err)
	}
	var report protocol.ToolsReport
	if err := json.Unmarshal(e.srv.WaitFrame(t, protocol.TypeToolsReport).Raw, &report); err != nil {
		t.Fatal(err)
	}
	if report.PushID != "p1" || len(report.Results) != 1 || report.Results[0].Status != protocol.ToolInstalled || report.Results[0].Rev != 2 {
		t.Fatalf("report = %+v", report)
	}
	data, err := os.ReadFile(filepath.Join(home, ".claude.json"))
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		McpServers map[string]map[string]any `json:"mcpServers"`
	}
	json.Unmarshal(data, &doc)
	if doc.McpServers["ctx"]["url"] != "https://mcp.example.com/mcp" {
		t.Fatalf(".claude.json = %s", data)
	}

	// a hand edit shows after the next welcome
	os.WriteFile(filepath.Join(home, ".claude.json"), []byte(`{"mcpServers":{"ctx":{"type":"http","url":"https://edited"}}}`), 0o600)
	e.welcome(1)
	var drift protocol.ToolsDrift
	json.Unmarshal(e.srv.WaitNthFrame(t, protocol.TypeToolsDrift, 2).Raw, &drift)
	if len(drift.Items) != 1 || drift.Items[0].Status != protocol.DriftChanged || drift.Items[0].Name != "ctx" {
		t.Fatalf("drift = %+v", drift)
	}
}

func TestToolsScanAnswers(t *testing.T) {
	home := isolateHome(t)
	os.WriteFile(filepath.Join(home, ".claude.json"), []byte(`{"mcpServers":{"mine":{"type":"stdio","command":"foo"}}}`), 0o600)
	e := newEnvWithCache(t, "[]", 1, t.TempDir())
	if err := e.srv.Send(protocol.ToolsScan{Type: protocol.TypeToolsScan, ScanID: "s1"}); err != nil {
		t.Fatal(err)
	}
	var found protocol.ToolsFound
	json.Unmarshal(e.srv.WaitFrame(t, protocol.TypeToolsFound).Raw, &found)
	if found.ScanID != "s1" || len(found.Items) != 1 || found.Items[0].Name != "mine" {
		t.Fatalf("found = %+v", found)
	}
}

// A Claude Code skill pushed from the hub reaches the agent's sessions as the hub plugin.
func TestPushedSkillReachesTheSession(t *testing.T) {
	isolateHome(t)
	cache := t.TempDir()
	e := newEnvWithCache(t, "[]", 1, cache)
	push := protocol.ToolsPush{Type: protocol.TypeToolsPush, PushID: "p1", Programs: []string{"claude_code"}, TakeOver: []string{},
		Tools: []protocol.ToolPayload{{ToolID: "t2", Name: "ui", Kind: "skill", Rev: 1,
			Files: []protocol.SkillFile{{Path: "SKILL.md", ContentB64: "eA=="}}}}}
	if err := e.srv.Send(push); err != nil {
		t.Fatal(err)
	}
	e.srv.WaitFrame(t, protocol.TypeToolsReport)
	e.startRun("run-1", "MEG-1", "read_only")
	e.finished("run-1")
	r := e.readReport()
	var meta struct {
		ClaudeCode struct {
			Options struct {
				Plugins []map[string]string `json:"plugins"`
			} `json:"options"`
		} `json:"claudeCode"`
	}
	if err := json.Unmarshal(r.Meta, &meta); err != nil {
		t.Fatal(err)
	}
	want := filepath.Join(cache, "hub-plugin")
	if len(meta.ClaudeCode.Options.Plugins) != 1 || meta.ClaudeCode.Options.Plugins[0]["path"] != want {
		t.Fatalf("meta = %s", r.Meta)
	}
	if _, err := os.Stat(filepath.Join(want, "skills", "ui", "SKILL.md")); err != nil {
		t.Fatal(err)
	}
}
