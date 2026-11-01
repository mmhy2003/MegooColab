package tools

import (
	"os"
	"strings"
	"testing"
)

func TestManifestRoundTrip(t *testing.T) {
	isolate(t)
	m, err := LoadManifest()
	if err != nil || len(m.Entries) != 0 {
		t.Fatalf("fresh manifest: %+v, %v", m, err)
	}
	m.Put(Entry{Program: "claude_code", Kind: "mcp", Name: "ctx", ToolID: "t1", Rev: 2, Fingerprint: "abc", ReadOnlySafe: true})
	m.Put(Entry{Program: "codex", Kind: "skill", Name: "ui", ToolID: "t2", Rev: 1, Fingerprint: "def"})
	m.Put(Entry{Program: "claude_code", Kind: "mcp", Name: "ctx", ToolID: "t1", Rev: 3, Fingerprint: "xyz"}) // replaces
	if err := m.Save(); err != nil {
		t.Fatal(err)
	}
	again, err := LoadManifest()
	if err != nil {
		t.Fatal(err)
	}
	if len(again.Entries) != 2 {
		t.Fatalf("entries = %+v", again.Entries)
	}
	if e := again.Find("claude_code", "mcp", "ctx"); e == nil || e.Rev != 3 || e.Fingerprint != "xyz" {
		t.Fatalf("find = %+v", e)
	}
	again.Remove("codex", "skill", "ui")
	if again.Find("codex", "skill", "ui") != nil || len(again.Entries) != 1 {
		t.Fatalf("after remove: %+v", again.Entries)
	}
}

func TestManifestPathUnderConfigDir(t *testing.T) {
	home := isolate(t)
	path, err := ManifestPath()
	if err != nil {
		t.Fatal(err)
	}
	cfg, _ := os.UserConfigDir()
	if !strings.HasPrefix(path, cfg) || !strings.HasPrefix(cfg, home) {
		t.Fatalf("manifest at %s, config dir %s, home %s", path, cfg, home)
	}
}
