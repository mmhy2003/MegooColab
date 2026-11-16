package tools

import (
	"encoding/json"
	"sort"

	"github.com/coder/acp-go-sdk"
)

// RunServers are the hub MCP servers the runner hands a run of program in session/new, load and resume. Claude Code
// runs start with settingSources: [], which also leaves ~/.claude.json's servers out, and OMP turns its own MCP
// config off in ACP mode, so the runner hands both their hub servers. Codex gets none: codex-acp loads every
// [mcp_servers.*] table of config.toml itself, and skips a passed server whose name the config already defines.
// Only the hub's own entries (the manifest's) go, as written in the program's file; a read-only run gets only
// those marked safe; never one named "megoocolab". An entry missing, unreadable or of another type is left out.
func RunServers(m *Manifest, program, home string, readOnly bool) []acp.McpServer {
	var path, label string
	switch program {
	case "claude_code":
		path, label = claudeJSON(home), ".claude.json"
	case "omp":
		path, label = ompMCPJSON(home), "mcp.json"
	default:
		return nil
	}
	servers, err := readServersAt(path, label)
	if err != nil {
		return nil
	}
	var names []string
	for _, e := range m.Entries {
		// the run's own server, with its run token, is the only "megoocolab"
		if e.Program == program && e.Kind == "mcp" && e.Name != megooColabServer && (e.ReadOnlySafe || !readOnly) {
			names = append(names, e.Name)
		}
	}
	sort.Strings(names)
	var out []acp.McpServer
	for _, name := range names {
		raw, ok := servers[name]
		if !ok {
			continue
		}
		var e struct {
			Type    string            `json:"type"`
			URL     string            `json:"url"`
			Headers map[string]string `json:"headers"`
			Command string            `json:"command"`
			Args    []string          `json:"args"`
			Env     map[string]string `json:"env"`
		}
		if json.Unmarshal(raw, &e) != nil {
			continue
		}
		switch {
		case e.Type == "http":
			headers := []acp.HttpHeader{}
			for _, k := range sortedKeys(e.Headers) {
				headers = append(headers, acp.HttpHeader{Name: k, Value: e.Headers[k]})
			}
			out = append(out, acp.McpServer{Http: &acp.McpServerHttpInline{Name: name, Url: e.URL, Headers: headers}})
		case e.Command != "":
			env := []acp.EnvVariable{}
			for _, k := range sortedKeys(e.Env) {
				env = append(env, acp.EnvVariable{Name: k, Value: e.Env[k]})
			}
			out = append(out, acp.McpServer{Stdio: &acp.McpServerStdio{Name: name, Command: e.Command,
				Args: nonNilSlice(e.Args), Env: env}})
		}
	}
	return out
}

func sortedKeys(m map[string]string) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
