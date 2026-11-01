package tools

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

func httpTool(name, key string) Tool {
	return Tool{ToolID: "t-" + name, Name: name, Kind: "mcp", Rev: 1,
		Mcp: &protocol.McpPayload{Transport: "http", URL: "https://mcp.example.com/mcp",
			Headers: map[string]string{"X-Key": key}, Args: []string{}, Env: map[string]string{}}}
}

func readJSON(t *testing.T, path string) map[string]any {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatal(err)
	}
	return m
}

func claude(t *testing.T) Translator {
	t.Helper()
	tr, ok := For("claude_code")
	if !ok || tr.Program() != "claude_code" {
		t.Fatal("no claude_code translator")
	}
	return tr
}

func TestClaudeInstallKeepsOtherKeys(t *testing.T) {
	home := isolate(t)
	path := filepath.Join(home, ".claude.json")
	start := `{"projects":{"x":{"a":1}},"oauthAccount":{"k":"v"},"mcpServers":{"mine":{"type":"stdio","command":"foo"}}}`
	if err := os.WriteFile(path, []byte(start), 0o600); err != nil {
		t.Fatal(err)
	}
	before := readJSON(t, path)
	fp, err := claude(t).InstallMCP(home, httpTool("ctx", "s3cret"))
	if err != nil || fp == "" {
		t.Fatalf("install: %q %v", fp, err)
	}
	after := readJSON(t, path)
	for _, k := range []string{"projects", "oauthAccount"} {
		if !reflect.DeepEqual(before[k], after[k]) {
			t.Fatalf("%s changed: %v -> %v", k, before[k], after[k])
		}
	}
	servers := after["mcpServers"].(map[string]any)
	if !reflect.DeepEqual(servers["mine"], before["mcpServers"].(map[string]any)["mine"]) {
		t.Fatalf("hand-made entry changed: %v", servers["mine"])
	}
	want := map[string]any{"type": "http", "url": "https://mcp.example.com/mcp", "headers": map[string]any{"X-Key": "s3cret"}}
	if !reflect.DeepEqual(servers["ctx"], want) {
		t.Fatalf("ctx = %v", servers["ctx"])
	}
	got, exists, err := claude(t).MCPFingerprint(home, "ctx")
	if err != nil || !exists || got != fp {
		t.Fatalf("fingerprint %q %v %v, want %q", got, exists, err, fp)
	}
}

func TestClaudeInstallStdioAndFreshFile(t *testing.T) {
	home := isolate(t)
	tool := Tool{Name: "pw", Kind: "mcp", Mcp: &protocol.McpPayload{Transport: "stdio", Command: "node",
		Args: []string{"server.js"}, Env: map[string]string{"A": "1"}, Headers: map[string]string{}}}
	if _, err := claude(t).InstallMCP(home, tool); err != nil {
		t.Fatal(err)
	}
	got := readJSON(t, filepath.Join(home, ".claude.json"))["mcpServers"].(map[string]any)["pw"]
	want := map[string]any{"type": "stdio", "command": "node", "args": []any{"server.js"}, "env": map[string]any{"A": "1"}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("pw = %v", got)
	}
}

func TestClaudeRemoveOnlyOurs(t *testing.T) {
	home := isolate(t)
	path := filepath.Join(home, ".claude.json")
	os.WriteFile(path, []byte(`{"mcpServers":{"mine":{"type":"stdio","command":"foo"}}}`), 0o600)
	tr := claude(t)
	if _, err := tr.InstallMCP(home, httpTool("ctx", "k")); err != nil {
		t.Fatal(err)
	}
	if err := tr.RemoveMCP(home, "ctx"); err != nil {
		t.Fatal(err)
	}
	servers := readJSON(t, path)["mcpServers"].(map[string]any)
	if _, ok := servers["ctx"]; ok || servers["mine"] == nil {
		t.Fatalf("servers = %v", servers)
	}
	if _, exists, _ := tr.MCPFingerprint(home, "ctx"); exists {
		t.Fatal("ctx still there")
	}
}

func TestClaudeFingerprintChangesOnHandEdit(t *testing.T) {
	home := isolate(t)
	tr := claude(t)
	fp, _ := tr.InstallMCP(home, httpTool("ctx", "k"))
	path := filepath.Join(home, ".claude.json")
	m := readJSON(t, path)
	m["mcpServers"].(map[string]any)["ctx"].(map[string]any)["url"] = "https://elsewhere"
	data, _ := json.Marshal(m)
	os.WriteFile(path, data, 0o600)
	got, exists, _ := tr.MCPFingerprint(home, "ctx")
	if !exists || got == fp {
		t.Fatalf("fingerprint did not change: %q", got)
	}
}

func TestWindowsCommand(t *testing.T) {
	cmd, args := WindowsCommand("windows", "npx", []string{"-y", "p"})
	if cmd != "cmd" || !reflect.DeepEqual(args, []string{"/c", "npx", "-y", "p"}) {
		t.Fatalf("windows npx: %s %v", cmd, args)
	}
	cmd, args = WindowsCommand("windows", "npx.cmd", []string{"p"})
	if cmd != "cmd" || !reflect.DeepEqual(args, []string{"/c", "npx.cmd", "p"}) {
		t.Fatalf("windows npx.cmd: %s %v", cmd, args)
	}
	for _, c := range []struct{ goos, cmd string }{{"linux", "npx"}, {"windows", "node"}, {"darwin", "pnpm"}} {
		got, gotArgs := WindowsCommand(c.goos, c.cmd, []string{"x"})
		if got != c.cmd || !reflect.DeepEqual(gotArgs, []string{"x"}) {
			t.Fatalf("%v: %s %v", c, got, gotArgs)
		}
	}
}

func TestClaudeSkillInstallReplace(t *testing.T) {
	home := isolate(t)
	tr := claude(t)
	v1 := []File{{Path: "SKILL.md", Content: []byte("v1")}, {Path: "a.md", Content: []byte("a")}}
	fp1, err := tr.InstallSkill(home, "ui", v1)
	if err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(home, ".claude", "skills", "ui")
	if data, _ := os.ReadFile(filepath.Join(dir, "a.md")); string(data) != "a" {
		t.Fatalf("a.md = %q", data)
	}
	v2 := []File{{Path: "SKILL.md", Content: []byte("v2")}, {Path: "sub/b.md", Content: []byte("b")}}
	fp2, err := tr.InstallSkill(home, "ui", v2)
	if err != nil || fp2 == fp1 {
		t.Fatalf("v2: %q %v", fp2, err)
	}
	if _, err := os.Stat(filepath.Join(dir, "a.md")); !os.IsNotExist(err) {
		t.Fatal("a.md left behind")
	}
	if data, _ := os.ReadFile(filepath.Join(dir, "sub", "b.md")); string(data) != "b" {
		t.Fatalf("sub/b.md = %q", data)
	}
	got, exists, _ := tr.SkillFingerprint(home, "ui")
	if !exists || got != fp2 {
		t.Fatalf("skill fingerprint %q, want %q", got, fp2)
	}
	entries, _ := os.ReadDir(filepath.Join(home, ".claude", "skills"))
	if len(entries) != 1 {
		t.Fatalf("left behind in skills: %v", entries)
	}
	if err := tr.RemoveSkill(home, "ui"); err != nil {
		t.Fatal(err)
	}
	if _, exists, _ := tr.SkillFingerprint(home, "ui"); exists {
		t.Fatal("skill still there")
	}
}

func TestClaudeSkillRefusesEscapingPaths(t *testing.T) {
	home := isolate(t)
	if _, err := claude(t).InstallSkill(home, "ui", []File{{Path: "../evil.md", Content: []byte("x")}}); err == nil {
		t.Fatal("escaping path accepted")
	}
}

func TestClaudeScan(t *testing.T) {
	home := isolate(t)
	cfg := `{"mcpServers":{
		"mine":{"type":"stdio","command":"cmd","args":["/c","npx","-y","pkg"],"env":{"K":"v"}},
		"web":{"type":"http","url":"https://w/mcp","headers":{"Authorization":"Bearer x"}},
		"old":{"type":"sse","url":"https://s"},
		"megoocolab":{"type":"http","url":"https://m"}}}`
	os.WriteFile(filepath.Join(home, ".claude.json"), []byte(cfg), 0o600)
	skill := filepath.Join(home, ".claude", "skills", "notes")
	os.MkdirAll(skill, 0o755)
	os.WriteFile(filepath.Join(skill, "SKILL.md"), []byte("---\nname: notes\n---\n"), 0o644)
	found, err := claude(t).ScanMCP(home)
	if err != nil {
		t.Fatal(err)
	}
	byName := map[string]protocol.FoundTool{}
	for _, f := range found {
		byName[f.Name] = f
	}
	if _, ok := byName["megoocolab"]; ok || len(found) != 3 {
		t.Fatalf("found = %+v", found)
	}
	if m := byName["mine"].Mcp; m == nil || m.Command != "npx" || !reflect.DeepEqual(m.Args, []string{"-y", "pkg"}) || m.Env["K"] != "v" {
		t.Fatalf("mine = %+v", byName["mine"].Mcp)
	}
	if m := byName["web"].Mcp; m == nil || m.Transport != "http" || m.Headers["Authorization"] != "Bearer x" {
		t.Fatalf("web = %+v", byName["web"].Mcp)
	}
	if byName["old"].Problem != "not supported: sse" {
		t.Fatalf("old = %+v", byName["old"])
	}
	skills, err := claude(t).ScanSkills(home)
	if err != nil || len(skills) != 1 || skills[0].Name != "notes" || len(skills[0].Files) != 1 {
		t.Fatalf("skills = %+v, %v", skills, err)
	}
}
