package jobs

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/tools"
)

// hubServers installs two hub MCP servers for OMP the way a push leaves them: entries in mcp.json and the manifest.
func hubServers(t *testing.T, home string) {
	t.Helper()
	dir := filepath.Join(home, ".omp", "agent")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	cfg := `{"mcpServers":{"docs":{"type":"http","url":"https://d/mcp"},"db":{"type":"stdio","command":"node","args":["db.js"]},"mine":{"type":"http","url":"https://m"}}}`
	if err := os.WriteFile(filepath.Join(dir, "mcp.json"), []byte(cfg), 0o600); err != nil {
		t.Fatal(err)
	}
	m, err := tools.LoadManifest()
	if err != nil {
		t.Fatal(err)
	}
	m.Put(tools.Entry{Program: "omp", Kind: "mcp", Name: "docs", ReadOnlySafe: true})
	m.Put(tools.Entry{Program: "omp", Kind: "mcp", Name: "db"})
	m.Put(tools.Entry{Program: "claude_code", Kind: "mcp", Name: "docs", ReadOnlySafe: true})
	if err := m.Save(); err != nil {
		t.Fatal(err)
	}
}

func sessionServers(t *testing.T, e *env) []string {
	t.Helper()
	var servers []struct {
		Name string `json:"name"`
	}
	r := e.finalReport()
	if err := json.Unmarshal(r.McpServers, &servers); err != nil {
		t.Fatalf("mcp servers = %s: %v", r.McpServers, err)
	}
	names := []string{}
	for _, s := range servers {
		names = append(names, s.Name)
	}
	sort.Strings(names)
	return names
}

func TestOmpRunGetsHubServers(t *testing.T) {
	home := isolateHome(t)
	hubServers(t, home)
	for _, c := range []struct {
		policy string
		want   []string
	}{{"workspace", []string{"db", "docs"}}, {"read_only", []string{"docs"}}} {
		e := newEnvWithCache(t, "[]", 1, t.TempDir())
		e.welcomeAs(1, "omp")
		e.startRun("r-"+c.policy, "MEG-1", c.policy)
		if f := e.finished("r-" + c.policy); f.Outcome != "completed" {
			t.Fatalf("%s: run = %+v", c.policy, f)
		}
		if got := sessionServers(t, e); !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: servers = %v, want %v", c.policy, got, c.want)
		}
	}
}

func TestClaudeRunGetsNoHubServers(t *testing.T) {
	home := isolateHome(t)
	hubServers(t, home)
	e := newEnvWithCache(t, "[]", 1, t.TempDir())
	e.startRun("r1", "MEG-1", "workspace")
	if f := e.finished("r1"); f.Outcome != "completed" {
		t.Fatalf("run = %+v", f)
	}
	if got := sessionServers(t, e); len(got) != 0 {
		t.Fatalf("servers = %v", got)
	}
}
