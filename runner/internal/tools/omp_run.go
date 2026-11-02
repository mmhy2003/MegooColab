package tools

import (
	"encoding/json"
	"sort"

	"github.com/coder/acp-go-sdk"
)

// OmpRunServers are the hub MCP servers an OMP run gets in session/new: OMP turns its own MCP config off in ACP
// mode, so the runner hands them over. Only the hub's own entries (the manifest's) go, as written in mcp.json with
// their keys; a read-only run gets only those marked safe in read-only runs. An entry missing or unreadable is
// left out.
func OmpRunServers(m *Manifest, home string, readOnly bool) []acp.McpServer {
	servers, err := readServersAt(ompMCPJSON(home), "mcp.json")
	if err != nil {
		return nil
	}
	var names []string
	for _, e := range m.Entries {
		if e.Program == "omp" && e.Kind == "mcp" && (e.ReadOnlySafe || !readOnly) {
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
