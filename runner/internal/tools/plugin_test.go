package tools

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestSyncPluginCopiesOnlyManagedClaudeSkills(t *testing.T) {
	home := isolate(t)
	cache := t.TempDir()
	m := manifest(t)
	if dir, err := SyncPlugin(cache, home, m); err != nil || dir != "" {
		t.Fatalf("no skills: %q %v", dir, err)
	}
	if _, err := claude(t).InstallSkill(home, "ui", []File{{Path: "SKILL.md", Content: []byte("ui")}}); err != nil {
		t.Fatal(err)
	}
	m.Put(Entry{Program: "claude_code", Kind: "skill", Name: "ui"})
	m.Put(Entry{Program: "codex", Kind: "skill", Name: "codex-only"})
	hand := filepath.Join(home, ".claude", "skills", "mine")
	os.MkdirAll(hand, 0o755)
	os.WriteFile(filepath.Join(hand, "SKILL.md"), []byte("mine"), 0o644)

	dir, err := SyncPlugin(cache, home, m)
	if err != nil || dir != filepath.Join(cache, "hub-plugin") {
		t.Fatalf("dir %q %v", dir, err)
	}
	var meta map[string]any
	data, _ := os.ReadFile(filepath.Join(dir, ".claude-plugin", "plugin.json"))
	if json.Unmarshal(data, &meta) != nil || meta["name"] != "megoocolab-hub" {
		t.Fatalf("plugin.json = %s", data)
	}
	if got, _ := os.ReadFile(filepath.Join(dir, "skills", "ui", "SKILL.md")); string(got) != "ui" {
		t.Fatalf("ui = %q", got)
	}
	for _, name := range []string{"mine", "codex-only"} {
		if _, err := os.Stat(filepath.Join(dir, "skills", name)); !os.IsNotExist(err) {
			t.Fatalf("%s copied into the plugin", name)
		}
	}
	// the skill goes: so does the plugin
	m.Remove("claude_code", "skill", "ui")
	if dir, err := SyncPlugin(cache, home, m); err != nil || dir != "" {
		t.Fatalf("after removal: %q %v", dir, err)
	}
	if _, err := os.Stat(filepath.Join(cache, "hub-plugin")); !os.IsNotExist(err) {
		t.Fatal("plugin folder left behind")
	}
}

func TestSafeServers(t *testing.T) {
	m := &Manifest{Entries: []Entry{
		{Program: "claude_code", Kind: "mcp", Name: "ctx", ReadOnlySafe: true},
		{Program: "claude_code", Kind: "mcp", Name: "writer"},
		{Program: "codex", Kind: "mcp", Name: "cdx", ReadOnlySafe: true},
		{Program: "claude_code", Kind: "skill", Name: "ui", ReadOnlySafe: true},
	}}
	if got := SafeServers(m, "claude_code"); len(got) != 1 || got[0] != "ctx" {
		t.Fatalf("claude = %v", got)
	}
	if got := SafeServers(m, "codex"); len(got) != 1 || got[0] != "cdx" {
		t.Fatalf("codex = %v", got)
	}
}
