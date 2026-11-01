package tools

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// Plan 24 final review: each test pins a finding.

func TestApplyKeepLeavesTheEntryAlone(t *testing.T) {
	home := isolate(t)
	m := manifest(t)
	Apply(home, m, []string{"claude_code"}, []Tool{httpTool("ctx", "k")}, nil, nil)
	fp, _, _ := claude(t).MCPFingerprint(home, "ctx")
	results := Apply(home, m, []string{"claude_code"}, nil, nil, []string{"ctx"})
	if len(results) != 0 {
		t.Fatalf("results = %+v", results)
	}
	if got, exists, _ := claude(t).MCPFingerprint(home, "ctx"); !exists || got != fp {
		t.Fatal("a kept tool was removed or changed")
	}
	if manifest(t).Find("claude_code", "mcp", "ctx") == nil {
		t.Fatal("a kept tool left the manifest")
	}
}

func TestReplaceTableKeepsCommentsOfTheNextTable(t *testing.T) {
	doc := "[mcp_servers.ctx]\nurl = \"u\"\n# ctx's own note\nx = 1\n\n# my other server\n[mcp_servers.other]\ncommand = \"o\"\n"
	out := string(replaceTable([]byte(doc), "ctx", nil))
	if !strings.Contains(out, "# my other server\n[mcp_servers.other]") || strings.Contains(out, "ctx's own note") {
		t.Fatalf("result:\n%s", out)
	}
}

func TestCodexRefusesWhatItCannotReplace(t *testing.T) {
	home := isolate(t)
	path := filepath.Join(home, ".codex", "config.toml")
	os.MkdirAll(filepath.Dir(path), 0o700)
	for _, doc := range []string{
		"[mcp_servers]\nctx = { command = \"x\" }\n",
		"mcp_servers.ctx.command = \"x\"\n",
	} {
		os.WriteFile(path, []byte(doc), 0o600)
		if _, err := codexTr(t).InstallMCP(home, httpTool("ctx", "k")); err == nil {
			t.Fatalf("installed over:\n%s", doc)
		}
		if data, _ := os.ReadFile(path); string(data) != doc {
			t.Fatalf("file changed:\n%s", data)
		}
	}
}

func TestSyncPluginSwapsAndSkipsWhenUnchanged(t *testing.T) {
	home := isolate(t)
	cache := t.TempDir()
	m := manifest(t)
	fp, _ := claude(t).InstallSkill(home, "ui", []File{{Path: "SKILL.md", Content: []byte("ui")}})
	m.Put(Entry{Program: "claude_code", Kind: "skill", Name: "ui", Fingerprint: fp})
	dir, err := SyncPlugin(cache, home, m)
	if err != nil || dir == "" {
		t.Fatal(dir, err)
	}
	marker := filepath.Join(dir, "marker")
	os.WriteFile(marker, []byte("x"), 0o644)
	if again, _ := SyncPlugin(cache, home, m); again != dir {
		t.Fatal(again)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatal("rebuilt although nothing changed")
	}
	fp2, _ := claude(t).InstallSkill(home, "ui", []File{{Path: "SKILL.md", Content: []byte("ui v2")}})
	m.Put(Entry{Program: "claude_code", Kind: "skill", Name: "ui", Fingerprint: fp2})
	if again, _ := SyncPlugin(cache, home, m); again != dir {
		t.Fatal(again)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("not rebuilt after a change")
	}
	if got, _ := os.ReadFile(filepath.Join(dir, "skills", "ui", "SKILL.md")); string(got) != "ui v2" {
		t.Fatalf("SKILL.md = %q", got)
	}
	entries, _ := os.ReadDir(cache)
	if len(entries) != 1 {
		t.Fatalf("left behind in the cache: %v", entries)
	}
}

func TestScanLimits(t *testing.T) {
	home := isolate(t)
	many := filepath.Join(home, ".claude", "skills", "many")
	os.MkdirAll(many, 0o755)
	os.WriteFile(filepath.Join(many, "SKILL.md"), []byte("x"), 0o644)
	for i := range 100 {
		os.WriteFile(filepath.Join(many, fmt.Sprintf("f%d.md", i)), []byte("y"), 0o644)
	}
	for _, n := range []string{"a", "b"} {
		dir := filepath.Join(home, ".claude", "skills", n)
		os.MkdirAll(dir, 0o755)
		os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte(strings.Repeat("z", 600)), 0o644)
	}
	old := scanBudget
	scanBudget = 1000
	t.Cleanup(func() { scanBudget = old })
	found := Scan(home, manifest(t))
	by := map[string]protocol.FoundTool{}
	for _, f := range found {
		by[f.Name] = f
	}
	if by["many"].Problem != "too many files" || by["many"].Files != nil {
		t.Fatalf("many = %+v", by["many"].Problem)
	}
	if by["a"].Files == nil || by["b"].Problem != "too large to send" || by["b"].Files != nil {
		t.Fatalf("a = %q, b = %q", by["a"].Problem, by["b"].Problem)
	}
}

var _ = time.Second
