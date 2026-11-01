package tools

import (
	"errors"
	"fmt"
	"path/filepath"
	"runtime"
	"sort"

	toml "github.com/pelletier/go-toml/v2"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// codex writes MCP servers as [mcp_servers.<name>] tables of $CODEX_HOME/config.toml, editing only those
// tables' lines, and skills into ~/.agents/skills/<name>/ (Codex's user skills root; $CODEX_HOME/skills is
// its older place, still read by a scan).
type codex struct{}

func init() { register(codex{}) }

func (codex) Program() string { return "codex" }

func codexConfig(home string) string { return filepath.Join(CodexHome(home), "config.toml") }

func codexSkills(home string) string { return filepath.Join(home, ".agents", "skills") }

func codexPayload(m *protocol.McpPayload) protocol.McpPayload {
	out := *m
	if out.Transport == "stdio" {
		out.Command, out.Args = WindowsCommand(runtime.GOOS, m.Command, m.Args)
	}
	return out
}

// codexServers parses a config.toml's mcp_servers tables.
func codexServers(data []byte) (map[string]any, error) {
	var doc map[string]any
	if err := toml.Unmarshal(data, &doc); err != nil {
		return nil, errors.New("config.toml could not be read") // the parser's message may quote the file
	}
	servers, _ := doc["mcp_servers"].(map[string]any)
	if servers == nil {
		servers = map[string]any{}
	}
	return servers, nil
}

func (c codex) InstallMCP(home string, t Tool) (string, error) {
	if t.Mcp == nil {
		return "", fmt.Errorf("%s has no MCP setup", t.Name)
	}
	block := renderCodexBlock(t.Name, codexPayload(t.Mcp))
	written, err := codexServers(block)
	if err != nil {
		return "", err
	}
	want := fingerprintJSON(written[t.Name])
	err = ReplaceFile(codexConfig(home), func(old []byte) ([]byte, error) {
		if len(old) > 0 {
			if _, err := codexServers(old); err != nil {
				return nil, err // never rewrite a file we cannot read
			}
		}
		next := replaceTable(old, t.Name, block)
		// a definition we cannot see as a table of its own (inline, dotted keys) would now clash: never write that
		if got, err := codexServers(next); err != nil || fingerprintJSON(got[t.Name]) != want {
			return nil, fmt.Errorf("config.toml defines %s in a way the runner cannot replace", t.Name)
		}
		return next, nil
	}, true)
	if err != nil {
		return "", err
	}
	return fingerprintJSON(written[t.Name]), nil
}

func (c codex) RemoveMCP(home, name string) error {
	if _, exists, err := c.MCPFingerprint(home, name); err != nil || !exists {
		return err
	}
	return ReplaceFile(codexConfig(home), func(old []byte) ([]byte, error) {
		next := replaceTable(old, name, nil)
		if got, err := codexServers(next); err != nil || got[name] != nil {
			return nil, fmt.Errorf("config.toml defines %s in a way the runner cannot remove", name)
		}
		return next, nil
	}, true)
}

func readCodexServers(home string) (map[string]any, error) {
	st, err := stampOf(codexConfig(home))
	if err != nil || !st.exists {
		return map[string]any{}, err
	}
	return codexServers(st.data)
}

func (codex) MCPFingerprint(home, name string) (string, bool, error) {
	servers, err := readCodexServers(home)
	if err != nil {
		return "", false, err
	}
	table, ok := servers[name]
	if !ok {
		return "", false, nil
	}
	return fingerprintJSON(table), true, nil
}

func (codex) InstallSkill(home, name string, files []File) (string, error) {
	return installSkillDir(codexSkills(home), name, files)
}

func (codex) RemoveSkill(home, name string) error { return removeSkillDir(codexSkills(home), name) }

func (codex) SkillFingerprint(home, name string) (string, bool, error) {
	return skillFingerprint(filepath.Join(codexSkills(home), name))
}

func stringMap(v any) map[string]string {
	out := map[string]string{}
	m, _ := v.(map[string]any)
	for k, val := range m {
		if s, ok := val.(string); ok {
			out[k] = s
		}
	}
	return out
}

func stringList(v any) []string {
	out := []string{}
	list, _ := v.([]any)
	for _, val := range list {
		if s, ok := val.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func (codex) ScanMCP(home string) ([]protocol.FoundTool, error) {
	servers, err := readCodexServers(home)
	if err != nil {
		return nil, err
	}
	names := make([]string, 0, len(servers))
	for n := range servers {
		names = append(names, n)
	}
	sort.Strings(names)
	var out []protocol.FoundTool
	for _, name := range names {
		if name == megooColabServer {
			continue
		}
		found := protocol.FoundTool{Program: "codex", Kind: "mcp", Name: name}
		table, _ := servers[name].(map[string]any)
		url, _ := table["url"].(string)
		command, _ := table["command"].(string)
		switch {
		case table == nil:
			found.Problem = "unreadable"
		case table["bearer_token_env_var"] != nil:
			found.Problem = "not supported: bearer_token_env_var"
		case url != "":
			found.Mcp = &protocol.McpPayload{Transport: "http", URL: url, Headers: stringMap(table["http_headers"]),
				Args: []string{}, Env: map[string]string{}}
		case command != "":
			cmd, args := unwrapWindowsCommand(command, stringList(table["args"]))
			found.Mcp = &protocol.McpPayload{Transport: "stdio", Command: cmd, Args: nonNilSlice(args),
				Env: stringMap(table["env"]), Headers: map[string]string{}}
		default:
			found.Problem = "unreadable"
		}
		out = append(out, found)
	}
	return out, nil
}

func (codex) ScanSkills(home string) ([]protocol.FoundTool, error) {
	return scanSkills("codex", codexSkills(home), filepath.Join(CodexHome(home), "skills")), nil
}
