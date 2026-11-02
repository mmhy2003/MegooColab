package tools

import (
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"

	"github.com/coder/acp-go-sdk"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

func omp(t *testing.T) Translator {
	t.Helper()
	tr, ok := For("omp")
	if !ok || tr.Program() != "omp" {
		t.Fatal("no omp translator")
	}
	return tr
}

func ompJSON(home string) string { return filepath.Join(home, ".omp", "agent", "mcp.json") }

func writeOmpJSON(t *testing.T, home, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(ompJSON(home)), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(ompJSON(home), []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestOmpAgentDirFromOmp(t *testing.T) {
	home := isolate(t)
	dir := filepath.Join(home, "elsewhere", "agent")
	ompConfigPath = func() (string, error) { return dir + "\n", nil }
	if got := OmpAgentDir(home); got != dir {
		t.Fatalf("got %q, want %q", got, dir)
	}
	ompConfigPath = func() (string, error) { return "relative/agent", nil } // not a path to trust
	if got := OmpAgentDir(home); got != filepath.Join(home, ".omp", "agent") {
		t.Fatalf("relative answer: got %q", got)
	}
}

func TestOmpAgentDirRule(t *testing.T) {
	home := isolate(t)
	cfg, over := filepath.Join(home, "c"), filepath.Join(home, "a")
	cases := []struct {
		env  map[string]string
		want string
	}{
		{nil, filepath.Join(home, ".omp", "agent")},
		{map[string]string{"PI_CONFIG_DIR": cfg}, filepath.Join(cfg, "agent")},
		{map[string]string{"OMP_PROFILE": "work"}, filepath.Join(home, ".omp", "profiles", "work", "agent")},
		{map[string]string{"PI_PROFILE": "work"}, filepath.Join(home, ".omp", "profiles", "work", "agent")},
		{map[string]string{"PI_CODING_AGENT_DIR": over}, over},
		// a named profile derives its own folder: the default profile's override does not apply
		{map[string]string{"OMP_PROFILE": "work", "PI_CODING_AGENT_DIR": over}, filepath.Join(home, ".omp", "profiles", "work", "agent")},
	}
	for _, c := range cases {
		for _, k := range []string{"PI_CONFIG_DIR", "OMP_PROFILE", "PI_PROFILE", "PI_CODING_AGENT_DIR"} {
			t.Setenv(k, c.env[k])
		}
		if got := OmpAgentDir(home); got != c.want {
			t.Errorf("%v: got %q, want %q", c.env, got, c.want)
		}
	}
}

func TestOmpInstallHttpAndStdio(t *testing.T) {
	home := isolate(t)
	if _, err := omp(t).InstallMCP(home, httpTool("docs", "s3cret")); err != nil {
		t.Fatal(err)
	}
	stdio := Tool{Name: "fs", Kind: "mcp", Mcp: &protocol.McpPayload{Transport: "stdio", Command: "node",
		Args: []string{"server.js"}, Env: map[string]string{"A": "1"}, Headers: map[string]string{}}}
	if _, err := omp(t).InstallMCP(home, stdio); err != nil {
		t.Fatal(err)
	}
	servers := readJSON(t, ompJSON(home))["mcpServers"].(map[string]any)
	if want := (map[string]any{"type": "http", "url": "https://mcp.example.com/mcp", "headers": map[string]any{"X-Key": "s3cret"}}); !reflect.DeepEqual(servers["docs"], want) {
		t.Fatalf("docs = %v", servers["docs"])
	}
	if want := (map[string]any{"type": "stdio", "command": "node", "args": []any{"server.js"}, "env": map[string]any{"A": "1"}}); !reflect.DeepEqual(servers["fs"], want) {
		t.Fatalf("fs = %v", servers["fs"])
	}
}

func TestOmpInstallKeepsOtherEntries(t *testing.T) {
	home := isolate(t)
	writeOmpJSON(t, home, `{"$schema":"https://example.com/mcp-schema.json","mcpServers":{"mine":{"type":"stdio","command":"foo"}}}`)
	before := readJSON(t, ompJSON(home))
	if _, err := omp(t).InstallMCP(home, httpTool("docs", "k")); err != nil {
		t.Fatal(err)
	}
	if mine := readJSON(t, ompJSON(home))["mcpServers"].(map[string]any)["mine"]; !reflect.DeepEqual(mine, before["mcpServers"].(map[string]any)["mine"]) {
		t.Fatalf("hand-made entry changed: %v", mine)
	}
	if err := omp(t).RemoveMCP(home, "docs"); err != nil {
		t.Fatal(err)
	}
	if after := readJSON(t, ompJSON(home)); !reflect.DeepEqual(before, after) {
		t.Fatalf("file changed: %v -> %v", before, after)
	}
}

func TestOmpInstallWindowsWrapsNpx(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("npx is wrapped in cmd /c on Windows only")
	}
	home := isolate(t)
	tool := Tool{Name: "pw", Kind: "mcp", Mcp: &protocol.McpPayload{Transport: "stdio", Command: "npx",
		Args: []string{"-y", "pkg"}, Env: map[string]string{}, Headers: map[string]string{}}}
	if _, err := omp(t).InstallMCP(home, tool); err != nil {
		t.Fatal(err)
	}
	got := readJSON(t, ompJSON(home))["mcpServers"].(map[string]any)["pw"].(map[string]any)
	if got["command"] != "cmd" || !reflect.DeepEqual(got["args"], []any{"/c", "npx", "-y", "pkg"}) {
		t.Fatalf("pw = %v", got)
	}
	found, err := omp(t).ScanMCP(home)
	if err != nil || len(found) != 1 || found[0].Mcp.Command != "npx" || !reflect.DeepEqual(found[0].Mcp.Args, []string{"-y", "pkg"}) {
		t.Fatalf("scan = %+v %v", found, err)
	}
}

func TestOmpMCPJSONIsPrivate(t *testing.T) {
	home := isolate(t)
	if _, err := omp(t).InstallMCP(home, httpTool("docs", "k")); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(ompJSON(home))
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm() != 0o600 {
		t.Fatalf("mode = %v, want 0600", info.Mode().Perm())
	}
}

func TestOmpSkillsInstallScanRemove(t *testing.T) {
	home := isolate(t)
	files := []File{{Path: "SKILL.md", Content: []byte("---\nname: ui\ndescription: UI help\n---\nBody\n")}}
	fp, err := omp(t).InstallSkill(home, "ui", files)
	if err != nil || fp == "" {
		t.Fatalf("install: %q %v", fp, err)
	}
	if _, err := os.Stat(filepath.Join(home, ".omp", "agent", "skills", "ui", "SKILL.md")); err != nil {
		t.Fatal(err)
	}
	if got, ok, err := omp(t).SkillFingerprint(home, "ui"); err != nil || !ok || got != fp {
		t.Fatalf("fingerprint %q %v %v", got, ok, err)
	}
	found, err := omp(t).ScanSkills(home)
	if err != nil || len(found) != 1 || found[0].Program != "omp" || found[0].Name != "ui" {
		t.Fatalf("scan = %+v %v", found, err)
	}
	if err := omp(t).RemoveSkill(home, "ui"); err != nil {
		t.Fatal(err)
	}
	if _, ok, _ := omp(t).SkillFingerprint(home, "ui"); ok {
		t.Fatal("skill still there")
	}
}

func TestOmpScanIgnoresMegooColabAndOtherPrograms(t *testing.T) {
	home := isolate(t)
	writeOmpJSON(t, home, `{"mcpServers":{"megoocolab":{"type":"http","url":"https://m"},"docs":{"type":"http","url":"https://d"}}}`)
	claudeSkill := filepath.Join(home, ".claude", "skills", "ui")
	if err := os.MkdirAll(claudeSkill, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(claudeSkill, "SKILL.md"), []byte("---\nname: ui\ndescription: d\n---\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	mcp, err := omp(t).ScanMCP(home)
	if err != nil || len(mcp) != 1 || mcp[0].Name != "docs" || mcp[0].Program != "omp" {
		t.Fatalf("mcp = %+v %v", mcp, err)
	}
	if skills, _ := omp(t).ScanSkills(home); len(skills) != 0 {
		t.Fatalf("skills = %+v", skills)
	}
}

func runServersSetup(t *testing.T) (string, *Manifest) {
	t.Helper()
	home := isolate(t)
	writeOmpJSON(t, home, `{"mcpServers":{
		"docs":{"type":"http","url":"https://d/mcp","headers":{"X-Key":"k","A":"1"}},
		"db":{"type":"stdio","command":"node","args":["db.js"],"env":{"PW":"p"}},
		"mine":{"type":"http","url":"https://mine"}}}`)
	m := &Manifest{Entries: []Entry{
		{Program: "omp", Kind: "mcp", Name: "docs", ReadOnlySafe: true},
		{Program: "omp", Kind: "mcp", Name: "db"},
		{Program: "omp", Kind: "mcp", Name: "gone", ReadOnlySafe: true},
		{Program: "claude_code", Kind: "mcp", Name: "mine", ReadOnlySafe: true},
		{Program: "omp", Kind: "skill", Name: "ui"},
	}}
	return home, m
}

func serverNames(servers []acp.McpServer) []string {
	var out []string
	for _, s := range servers {
		switch {
		case s.Http != nil:
			out = append(out, s.Http.Name)
		case s.Stdio != nil:
			out = append(out, s.Stdio.Name)
		}
	}
	return out
}

func TestOmpRunServersWorkspaceHasAll(t *testing.T) {
	home, m := runServersSetup(t)
	servers := OmpRunServers(m, home, false)
	if got := serverNames(servers); !reflect.DeepEqual(got, []string{"db", "docs"}) {
		t.Fatalf("servers = %v", got)
	}
	db, docs := servers[0].Stdio, servers[1].Http
	if db == nil || db.Command != "node" || !reflect.DeepEqual(db.Args, []string{"db.js"}) ||
		!reflect.DeepEqual(db.Env, []acp.EnvVariable{{Name: "PW", Value: "p"}}) {
		t.Fatalf("db = %+v", db)
	}
	if docs == nil || docs.Url != "https://d/mcp" ||
		!reflect.DeepEqual(docs.Headers, []acp.HttpHeader{{Name: "A", Value: "1"}, {Name: "X-Key", Value: "k"}}) {
		t.Fatalf("docs = %+v", docs)
	}
}

func TestOmpRunServersReadOnlyOnlySafe(t *testing.T) {
	home, m := runServersSetup(t)
	if got := serverNames(OmpRunServers(m, home, true)); !reflect.DeepEqual(got, []string{"docs"}) {
		t.Fatalf("servers = %v", got)
	}
}

func TestOmpRunServersSkipsMissingOrUnreadable(t *testing.T) {
	home, m := runServersSetup(t)
	writeOmpJSON(t, home, `{"mcpServers":{"docs":"not an object","db":{"type":"stdio","command":"node"}}}`)
	if got := serverNames(OmpRunServers(m, home, false)); !reflect.DeepEqual(got, []string{"db"}) {
		t.Fatalf("servers = %v", got)
	}
	writeOmpJSON(t, home, `{broken`)
	if got := OmpRunServers(m, home, false); len(got) != 0 {
		t.Fatalf("servers from a broken file = %v", got)
	}
}

func TestOmpFingerprintMatchesInstall(t *testing.T) {
	home := isolate(t)
	fp, err := omp(t).InstallMCP(home, httpTool("docs", "k"))
	if err != nil {
		t.Fatal(err)
	}
	got, exists, err := omp(t).MCPFingerprint(home, "docs")
	if err != nil || !exists || got != fp {
		t.Fatalf("fingerprint %q %v %v, want %q", got, exists, err, fp)
	}
	if _, exists, _ := omp(t).MCPFingerprint(home, "nope"); exists {
		t.Fatal("missing entry exists")
	}
}
