package jobs

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
	"github.com/mmhy2003/megoocolab/runner/internal/tools"
)

// hubServers installs two hub MCP servers (docs, safe; db) for every program the way a push leaves them: entries in
// each program's own config and the manifest. The configs also hold a megoocolab entry and a hand-made one.
func hubServers(t *testing.T, home string) {
	t.Helper()
	write := func(path, content string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	cfg := `{"mcpServers":{"docs":{"type":"http","url":"https://d/mcp"},"db":{"type":"stdio","command":"node","args":["db.js"]},` +
		`"megoocolab":{"type":"http","url":"https://elsewhere"},"handmade":{"type":"http","url":"https://m"}}}`
	write(filepath.Join(home, ".claude.json"), cfg)
	write(filepath.Join(home, ".omp", "agent", "mcp.json"), cfg)
	write(filepath.Join(tools.CodexHome(home), "config.toml"),
		"[mcp_servers.docs]\nurl = \"https://d/mcp\"\n\n[mcp_servers.db]\ncommand = \"node\"\nargs = [\"db.js\"]\n")
	m, err := tools.LoadManifest()
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{"claude_code", "codex", "omp"} {
		m.Put(tools.Entry{Program: p, Kind: "mcp", Name: "docs", ReadOnlySafe: true})
		m.Put(tools.Entry{Program: p, Kind: "mcp", Name: "db"})
		m.Put(tools.Entry{Program: p, Kind: "mcp", Name: "megoocolab", ReadOnlySafe: true})
	}
	if err := m.Save(); err != nil {
		t.Fatal(err)
	}
}

type sessionServer struct {
	Name string `json:"name"`
	URL  string `json:"url"`
}

func sessionServerList(t *testing.T, e *env) []sessionServer {
	t.Helper()
	var servers []sessionServer
	r := e.finalReport()
	if err := json.Unmarshal(r.McpServers, &servers); err != nil {
		t.Fatalf("mcp servers = %s: %v", r.McpServers, err)
	}
	return servers
}

func sessionServers(t *testing.T, e *env) []string {
	t.Helper()
	names := []string{}
	for _, s := range sessionServerList(t, e) {
		names = append(names, s.Name)
	}
	sort.Strings(names)
	return names
}

func TestRunGetsHubServers(t *testing.T) {
	for _, c := range []struct {
		program, policy string
		want            []string
	}{
		{"claude_code", "workspace", []string{"db", "docs"}},
		{"claude_code", "read_only", []string{"docs"}},
		{"omp", "workspace", []string{"db", "docs"}},
		{"omp", "read_only", []string{"docs"}},
		// Codex loads its config.toml itself
		{"codex", "workspace", []string{}},
		{"codex", "read_only", []string{}},
	} {
		t.Run(c.program+"/"+c.policy, func(t *testing.T) {
			home := isolateHome(t)
			hubServers(t, home)
			e := newEnvWithCache(t, "[]", 1, t.TempDir())
			e.welcomeAs(1, c.program)
			e.startRun("r1", "MEG-1", c.policy)
			if f := e.finished("r1"); f.Outcome != "completed" {
				t.Fatalf("run = %+v", f)
			}
			if got := sessionServers(t, e); !reflect.DeepEqual(got, c.want) {
				t.Errorf("servers = %v, want %v", got, c.want)
			}
		})
	}
}

func TestResumedClaudeRunGetsHubServers(t *testing.T) {
	for name, c := range map[string]struct{ env, event string }{
		"session/load":   {"", "load:"},
		"session/resume": {"FAKEAGENT_RESUME", "resume:"},
	} {
		t.Run(name, func(t *testing.T) {
			home := isolateHome(t)
			hubServers(t, home)
			t.Setenv("FAKEAGENT_SESSIONS_DIR", t.TempDir())
			if c.env != "" {
				t.Setenv(c.env, "1")
			}
			e := newEnvWithCache(t, twoTurns, 1, t.TempDir())
			e.startRunWith("run-a", "MEG-9", func(rs *protocol.RunStart) { rs.Prompt = "first turn" })
			first := e.finished("run-a")
			e.startRunWith("run-b", "MEG-9", func(rs *protocol.RunStart) {
				rs.ResumeSessionID, rs.ResumePrompt = *first.SessionID, "continue please"
			})
			e.finished("run-b")
			if ev := e.finalReport().SessionEvents; len(ev) == 0 || !strings.HasPrefix(ev[0], c.event) {
				t.Fatalf("session events = %v, want %s...", ev, c.event)
			}
			if got := sessionServers(t, e); !reflect.DeepEqual(got, []string{"db", "docs"}) {
				t.Errorf("servers = %v", got)
			}
		})
	}
}

func TestWorkflowClaudeRunHasOneMegooColab(t *testing.T) {
	home := isolateHome(t)
	hubServers(t, home)
	ep := newMcpEndpoint(t)
	e := newEnvWithCache(t, "[]", 1, t.TempDir())
	e.startRunWith("r1", "MEG-1", withMcp(ep.URL+"/api/mcp"))
	if f := e.finished("r1"); f.Outcome != "completed" {
		t.Fatalf("run = %+v", f)
	}
	if got := sessionServers(t, e); !reflect.DeepEqual(got, []string{"db", "docs", "megoocolab"}) {
		t.Fatalf("servers = %v", got)
	}
	for _, s := range sessionServerList(t, e) {
		if s.Name == "megoocolab" && s.URL != ep.URL+"/api/mcp" {
			t.Errorf("megoocolab url = %q, want the run's own %q", s.URL, ep.URL+"/api/mcp")
		}
	}
}
