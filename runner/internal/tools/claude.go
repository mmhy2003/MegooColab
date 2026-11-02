package tools

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"runtime"
	"sort"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// megooColabServer is MegooColab's own MCP server name; it is never imported or touched.
const megooColabServer = "megoocolab"

// claudeCode writes MCP servers into the user-level mcpServers of ~/.claude.json and skills into
// ~/.claude/skills/<name>/. Every other key of ~/.claude.json is kept as it was.
type claudeCode struct{}

func init() { register(claudeCode{}) }

func (claudeCode) Program() string { return "claude_code" }

func claudeJSON(home string) string { return filepath.Join(home, ".claude.json") }

func claudeSkills(home string) string { return filepath.Join(home, ".claude", "skills") }

// claudeEntry is the mcpServers entry Claude Code reads for a tool.
func claudeEntry(m *protocol.McpPayload) map[string]any {
	if m.Transport == "http" {
		e := map[string]any{"type": "http", "url": m.URL}
		if len(m.Headers) > 0 {
			e["headers"] = m.Headers
		}
		return e
	}
	command, args := WindowsCommand(runtime.GOOS, m.Command, m.Args)
	e := map[string]any{"type": "stdio", "command": command, "args": args}
	if len(m.Env) > 0 {
		e["env"] = m.Env
	}
	return e
}

// editServers decodes a JSON file with a top-level mcpServers object (~/.claude.json, OMP's mcp.json) keeping
// unrelated keys as raw bytes, lets edit change mcpServers, and encodes it back. label names the file in errors.
func editServers(label string, old []byte, edit func(servers map[string]json.RawMessage) error) ([]byte, error) {
	doc := map[string]json.RawMessage{}
	if len(old) > 0 {
		if err := json.Unmarshal(old, &doc); err != nil {
			return nil, fmt.Errorf("%s is not valid JSON: %w", label, err)
		}
	}
	servers := map[string]json.RawMessage{}
	if raw, ok := doc["mcpServers"]; ok && string(raw) != "null" {
		if err := json.Unmarshal(raw, &servers); err != nil {
			return nil, fmt.Errorf("%s mcpServers is not an object: %w", label, err)
		}
	}
	if err := edit(servers); err != nil {
		return nil, err
	}
	raw, err := json.Marshal(servers)
	if err != nil {
		return nil, err
	}
	doc["mcpServers"] = raw
	return json.MarshalIndent(doc, "", "  ")
}

func (c claudeCode) InstallMCP(home string, t Tool) (string, error) {
	if t.Mcp == nil {
		return "", fmt.Errorf("%s has no MCP setup", t.Name)
	}
	entry := claudeEntry(t.Mcp)
	err := ReplaceFile(claudeJSON(home), func(old []byte) ([]byte, error) {
		return editServers(".claude.json", old, func(servers map[string]json.RawMessage) error {
			raw, err := json.Marshal(entry)
			servers[t.Name] = raw
			return err
		})
	}, true)
	if err != nil {
		return "", err
	}
	return fingerprintJSON(entry), nil
}

func (c claudeCode) RemoveMCP(home, name string) error {
	if _, exists, err := c.MCPFingerprint(home, name); err != nil || !exists {
		return err
	}
	return ReplaceFile(claudeJSON(home), func(old []byte) ([]byte, error) {
		return editServers(".claude.json", old, func(servers map[string]json.RawMessage) error {
			delete(servers, name)
			return nil
		})
	}, true)
}

func readServers(home string) (map[string]json.RawMessage, error) {
	return readServersAt(claudeJSON(home), ".claude.json")
}

// readServersAt is the mcpServers object of the JSON file at path (none when the file does not exist).
func readServersAt(path, label string) (map[string]json.RawMessage, error) {
	st, err := stampOf(path)
	if err != nil || !st.exists {
		return map[string]json.RawMessage{}, err
	}
	var doc struct {
		McpServers map[string]json.RawMessage `json:"mcpServers"`
	}
	if err := json.Unmarshal(st.data, &doc); err != nil {
		return nil, fmt.Errorf("%s is not valid JSON: %w", label, err)
	}
	if doc.McpServers == nil {
		doc.McpServers = map[string]json.RawMessage{}
	}
	return doc.McpServers, nil
}

func (claudeCode) MCPFingerprint(home, name string) (string, bool, error) {
	servers, err := readServers(home)
	if err != nil {
		return "", false, err
	}
	raw, ok := servers[name]
	if !ok {
		return "", false, nil
	}
	return fingerprintJSON(raw), true, nil
}

func (claudeCode) InstallSkill(home, name string, files []File) (string, error) {
	return installSkillDir(claudeSkills(home), name, files)
}

func (claudeCode) RemoveSkill(home, name string) error {
	return removeSkillDir(claudeSkills(home), name)
}

func (claudeCode) SkillFingerprint(home, name string) (string, bool, error) {
	return skillFingerprint(filepath.Join(claudeSkills(home), name))
}

func (claudeCode) ScanMCP(home string) ([]protocol.FoundTool, error) {
	servers, err := readServers(home)
	if err != nil {
		return nil, err
	}
	return scanServers("claude_code", servers), nil
}

// scanServers reads mcpServers entries in Claude Code's shape (OMP's mcp.json uses the same), MegooColab's own
// server left out.
func scanServers(program string, servers map[string]json.RawMessage) []protocol.FoundTool {
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
		var e struct {
			Type    string            `json:"type"`
			URL     string            `json:"url"`
			Headers map[string]string `json:"headers"`
			Command string            `json:"command"`
			Args    []string          `json:"args"`
			Env     map[string]string `json:"env"`
		}
		found := protocol.FoundTool{Program: program, Kind: "mcp", Name: name}
		if err := json.Unmarshal(servers[name], &e); err != nil {
			found.Problem = "unreadable"
			out = append(out, found)
			continue
		}
		switch {
		case e.Type == "http":
			found.Mcp = &protocol.McpPayload{Transport: "http", URL: e.URL, Headers: nonNil(e.Headers), Args: []string{},
				Env: map[string]string{}}
		case e.Type == "stdio" || (e.Type == "" && e.Command != ""):
			command, args := unwrapWindowsCommand(e.Command, e.Args)
			found.Mcp = &protocol.McpPayload{Transport: "stdio", Command: command, Args: nonNilSlice(args),
				Env: nonNil(e.Env), Headers: map[string]string{}}
		default:
			found.Problem = "not supported: " + e.Type
		}
		out = append(out, found)
	}
	return out
}

func (claudeCode) ScanSkills(home string) ([]protocol.FoundTool, error) {
	return scanSkills("claude_code", claudeSkills(home)), nil
}

func nonNil(m map[string]string) map[string]string {
	if m == nil {
		return map[string]string{}
	}
	return m
}

func nonNilSlice(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}
