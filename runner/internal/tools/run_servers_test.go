package tools

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/coder/acp-go-sdk"
)

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

func TestRunServersOmpWorkspaceHasAll(t *testing.T) {
	home, m := runServersSetup(t)
	servers := RunServers(m, "omp", home, false)
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

func TestRunServersOmpReadOnlyOnlySafe(t *testing.T) {
	home, m := runServersSetup(t)
	if got := serverNames(RunServers(m, "omp", home, true)); !reflect.DeepEqual(got, []string{"docs"}) {
		t.Fatalf("servers = %v", got)
	}
}

func TestRunServersOmpNeverPassesMegooColab(t *testing.T) {
	home, m := runServersSetup(t)
	writeOmpJSON(t, home, `{"mcpServers":{"megoocolab":{"type":"http","url":"https://elsewhere"},"docs":{"type":"http","url":"https://d"}}}`)
	m.Put(Entry{Program: "omp", Kind: "mcp", Name: "megoocolab", ReadOnlySafe: true})
	// the run's own server, with its run token, is the only "megoocolab"
	if got := serverNames(RunServers(m, "omp", home, false)); !reflect.DeepEqual(got, []string{"docs"}) {
		t.Fatalf("servers = %v", got)
	}
}

func TestRunServersOmpSkipsMissingOrUnreadable(t *testing.T) {
	home, m := runServersSetup(t)
	writeOmpJSON(t, home, `{"mcpServers":{"docs":"not an object","db":{"type":"stdio","command":"node"}}}`)
	if got := serverNames(RunServers(m, "omp", home, false)); !reflect.DeepEqual(got, []string{"db"}) {
		t.Fatalf("servers = %v", got)
	}
	writeOmpJSON(t, home, `{broken`)
	if got := RunServers(m, "omp", home, false); len(got) != 0 {
		t.Fatalf("servers from a broken file = %v", got)
	}
}

// hubMCPServers is the same config for every program: hub entries docs (http, safe, header) and db (stdio, env),
// megoocolab (also in the manifest) and handmade (file only).
const hubMCPServers = `{"mcpServers":{
	"docs":{"type":"http","url":"https://d/mcp","headers":{"X-Key":"k"}},
	"db":{"type":"stdio","command":"node","args":["db.js"],"env":{"PW":"p"}},
	"megoocolab":{"type":"http","url":"https://elsewhere"},
	"handmade":{"type":"http","url":"https://h"}}}`

func hubManifest(program string) *Manifest {
	return &Manifest{Entries: []Entry{
		{Program: program, Kind: "mcp", Name: "docs", ReadOnlySafe: true},
		{Program: program, Kind: "mcp", Name: "db"},
		{Program: program, Kind: "mcp", Name: "megoocolab", ReadOnlySafe: true},
	}}
}

func TestRunServersPerProgram(t *testing.T) {
	for _, tc := range []struct {
		program string
		write   func(t *testing.T, home string)
	}{
		{"claude_code", func(t *testing.T, home string) {
			if err := os.WriteFile(filepath.Join(home, ".claude.json"), []byte(hubMCPServers), 0o600); err != nil {
				t.Fatal(err)
			}
		}},
		{"omp", func(t *testing.T, home string) { writeOmpJSON(t, home, hubMCPServers) }},
	} {
		t.Run(tc.program, func(t *testing.T) {
			home := isolate(t)
			tc.write(t, home)
			m := hubManifest(tc.program)
			servers := RunServers(m, tc.program, home, false)
			if got := serverNames(servers); !reflect.DeepEqual(got, []string{"db", "docs"}) {
				t.Fatalf("workspace servers = %v", got)
			}
			db, docs := servers[0].Stdio, servers[1].Http
			if db == nil || db.Command != "node" || !reflect.DeepEqual(db.Args, []string{"db.js"}) ||
				!reflect.DeepEqual(db.Env, []acp.EnvVariable{{Name: "PW", Value: "p"}}) {
				t.Fatalf("db = %+v", db)
			}
			if docs == nil || docs.Url != "https://d/mcp" ||
				!reflect.DeepEqual(docs.Headers, []acp.HttpHeader{{Name: "X-Key", Value: "k"}}) {
				t.Fatalf("docs = %+v", docs)
			}
			if got := serverNames(RunServers(m, tc.program, home, true)); !reflect.DeepEqual(got, []string{"docs"}) {
				t.Fatalf("read-only servers = %v", got)
			}
		})
	}
}

func TestRunServersCodexGetsNone(t *testing.T) {
	home := isolate(t)
	path := codexConfig(home)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	toml := "[mcp_servers.docs]\nurl = \"https://d/mcp\"\n\n[mcp_servers.db]\ncommand = \"node\"\n"
	if err := os.WriteFile(path, []byte(toml), 0o600); err != nil {
		t.Fatal(err)
	}
	// codex-acp loads config.toml's servers itself
	m := hubManifest("codex")
	for _, readOnly := range []bool{false, true} {
		if got := RunServers(m, "codex", home, readOnly); len(got) != 0 {
			t.Fatalf("readOnly=%v: servers = %v", readOnly, serverNames(got))
		}
	}
}

func TestRunServersInvalidClaudeJSON(t *testing.T) {
	home := isolate(t)
	if err := os.WriteFile(filepath.Join(home, ".claude.json"), []byte(`{broken`), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := RunServers(hubManifest("claude_code"), "claude_code", home, false); len(got) != 0 {
		t.Fatalf("servers from a broken file = %v", serverNames(got))
	}
}
