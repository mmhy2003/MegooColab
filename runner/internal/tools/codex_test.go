package tools

import (
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"

	toml "github.com/pelletier/go-toml/v2"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

const codexStart = `# my codex settings
model = "x"

[mcp_servers.other]
command = "foo"
args = ["--bar"]

[mcp_servers.ctx]
url = "https://old"

[mcp_servers.ctx.http_headers]
X-Key = "old"

[profiles.a]
model = "y"
`

func TestReplaceTableKeepsEverythingElse(t *testing.T) {
	block := []byte("[mcp_servers.ctx]\nurl = \"https://new\"\n")
	out := string(replaceTable([]byte(codexStart), "ctx", block))
	prefix := codexStart[:strings.Index(codexStart, "[mcp_servers.ctx]")]
	if !strings.HasPrefix(out, prefix) {
		t.Fatalf("before our table changed:\n%s", out)
	}
	if !strings.Contains(out, "[profiles.a]\nmodel = \"y\"\n") || strings.Contains(out, "https://old") || strings.Contains(out, `X-Key = "old"`) {
		t.Fatalf("result:\n%s", out)
	}
	if !strings.HasSuffix(out, "\n\n[mcp_servers.ctx]\nurl = \"https://new\"\n") {
		t.Fatalf("our table not appended once at the end:\n%s", out)
	}
	removed := string(replaceTable([]byte(codexStart), "ctx", nil))
	if strings.Contains(removed, "mcp_servers.ctx") || !strings.Contains(removed, "[mcp_servers.other]") {
		t.Fatalf("remove:\n%s", removed)
	}
	if again := string(replaceTable([]byte(out), "ctx", block)); again != out {
		t.Fatalf("not stable:\n%s\n---\n%s", out, again)
	}
}

func TestReplaceTableQuotedNames(t *testing.T) {
	doc := "[mcp_servers.\"a.b\"]\nurl = \"u\"\n\n[mcp_servers.a]\nurl = \"keep\"\n"
	out := string(replaceTable([]byte(doc), "a.b", nil))
	if strings.Contains(out, `"a.b"`) || !strings.Contains(out, `url = "keep"`) {
		t.Fatalf("result:\n%s", out)
	}
}

func TestRenderEscapes(t *testing.T) {
	m := protocol.McpPayload{Transport: "http", URL: `https://x/"q"`, Headers: map[string]string{"X Weird": "a\"b\\c\nd"},
		Args: []string{}, Env: map[string]string{}}
	block := renderCodexBlock("my.tool", m)
	var doc map[string]any
	if err := toml.Unmarshal(block, &doc); err != nil {
		t.Fatalf("does not parse: %v\n%s", err, block)
	}
	table := doc["mcp_servers"].(map[string]any)["my.tool"].(map[string]any)
	if table["url"] != `https://x/"q"` || table["http_headers"].(map[string]any)["X Weird"] != "a\"b\\c\nd" {
		t.Fatalf("parsed back: %v", table)
	}
}

func codexTr(t *testing.T) Translator {
	t.Helper()
	tr, ok := For("codex")
	if !ok {
		t.Fatal("no codex translator")
	}
	return tr
}

func TestCodexInstallFreshFile(t *testing.T) {
	home := isolate(t)
	tr := codexTr(t)
	tool := Tool{Name: "pw", Kind: "mcp", Mcp: &protocol.McpPayload{Transport: "stdio", Command: "npx",
		Args: []string{"-y", "pkg"}, Env: map[string]string{"K": "v"}, Headers: map[string]string{}}}
	fp, err := tr.InstallMCP(home, tool)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(home, ".codex", "config.toml")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := toml.Unmarshal(data, &doc); err != nil {
		t.Fatalf("%v\n%s", err, data)
	}
	table := doc["mcp_servers"].(map[string]any)["pw"].(map[string]any)
	wantCmd, wantArgs := "npx", []any{"-y", "pkg"}
	if runtime.GOOS == "windows" {
		wantCmd, wantArgs = "cmd", []any{"/c", "npx", "-y", "pkg"}
	}
	if table["command"] != wantCmd || !reflect.DeepEqual(table["args"], wantArgs) || table["env"].(map[string]any)["K"] != "v" {
		t.Fatalf("pw = %v", table)
	}
	if runtime.GOOS != "windows" {
		if info, _ := os.Stat(path); info.Mode().Perm() != 0o600 {
			t.Fatalf("mode %v", info.Mode().Perm())
		}
	}
	got, exists, err := tr.MCPFingerprint(home, "pw")
	if err != nil || !exists || got != fp {
		t.Fatalf("fingerprint %q %v %v want %q", got, exists, err, fp)
	}
	if err := tr.RemoveMCP(home, "pw"); err != nil {
		t.Fatal(err)
	}
	if _, exists, _ := tr.MCPFingerprint(home, "pw"); exists {
		t.Fatal("pw still there")
	}
}

func TestCodexKeepsTheRestOfTheFile(t *testing.T) {
	home := isolate(t)
	path := filepath.Join(home, ".codex", "config.toml")
	os.MkdirAll(filepath.Dir(path), 0o700)
	os.WriteFile(path, []byte(codexStart), 0o600)
	if _, err := codexTr(t).InstallMCP(home, httpTool("ctx", "new")); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(path)
	out := string(data)
	if !strings.HasPrefix(out, codexStart[:strings.Index(codexStart, "[mcp_servers.ctx]")]) || !strings.Contains(out, "[profiles.a]") {
		t.Fatalf("result:\n%s", out)
	}
}

func TestCodexHomeFromEnv(t *testing.T) {
	home := isolate(t)
	alt := filepath.Join(home, "elsewhere")
	t.Setenv("CODEX_HOME", alt)
	if _, err := codexTr(t).InstallMCP(home, httpTool("ctx", "k")); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(alt, "config.toml")); err != nil {
		t.Fatal(err)
	}
}

func TestCodexSkillsUnderAgents(t *testing.T) {
	home := isolate(t)
	if _, err := codexTr(t).InstallSkill(home, "ui", []File{{Path: "SKILL.md", Content: []byte("x")}}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(home, ".agents", "skills", "ui", "SKILL.md")); err != nil {
		t.Fatal(err)
	}
}

func TestCodexScan(t *testing.T) {
	home := isolate(t)
	path := filepath.Join(home, ".codex", "config.toml")
	os.MkdirAll(filepath.Dir(path), 0o700)
	os.WriteFile(path, []byte(codexStart+"\n[mcp_servers.tok]\nurl = \"https://t\"\nbearer_token_env_var = \"T\"\n"), 0o600)
	for _, dir := range []string{filepath.Join(home, ".agents", "skills", "a"), filepath.Join(home, ".codex", "skills", "b")} {
		os.MkdirAll(dir, 0o755)
		os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte("x"), 0o644)
	}
	found, err := codexTr(t).ScanMCP(home)
	if err != nil {
		t.Fatal(err)
	}
	byName := map[string]protocol.FoundTool{}
	for _, f := range found {
		byName[f.Name] = f
	}
	if m := byName["other"].Mcp; m == nil || m.Command != "foo" || !reflect.DeepEqual(m.Args, []string{"--bar"}) {
		t.Fatalf("other = %+v", byName["other"])
	}
	if m := byName["ctx"].Mcp; m == nil || m.URL != "https://old" || m.Headers["X-Key"] != "old" {
		t.Fatalf("ctx = %+v", byName["ctx"])
	}
	if byName["tok"].Problem != "not supported: bearer_token_env_var" {
		t.Fatalf("tok = %+v", byName["tok"])
	}
	skills, _ := codexTr(t).ScanSkills(home)
	names := []string{}
	for _, s := range skills {
		names = append(names, s.Name)
	}
	if !reflect.DeepEqual(names, []string{"a", "b"}) {
		t.Fatalf("skills = %v", names)
	}
}
