package tools

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"sort"
)

// pluginName is the local plugin that hands the hub's skills to MegooColab's Claude Code sessions. Those run
// with settingSources [] (adapters.SessionMeta), so ~/.claude/skills does not reach them; the plugin carries
// exactly the skills the hub installed, and nothing else from the person's own setup.
const pluginName = "megoocolab-hub"

func pluginDir(cacheRoot string) string { return filepath.Join(cacheRoot, "hub-plugin") }

// PluginDir is the hub plugin's folder when there is one, else "".
func PluginDir(cacheRoot string) string {
	dir := pluginDir(cacheRoot)
	if _, err := os.Stat(filepath.Join(dir, ".claude-plugin", "plugin.json")); err != nil {
		return ""
	}
	return dir
}

// SyncPlugin rebuilds the hub plugin from the Claude Code skills in the manifest, copied from where they are
// installed. With none, there is no plugin and it returns "".
func SyncPlugin(cacheRoot, home string, m *Manifest) (string, error) {
	dir := pluginDir(cacheRoot)
	if err := os.RemoveAll(dir); err != nil {
		return "", err
	}
	var names []string
	for _, e := range m.Entries {
		if e.Program == "claude_code" && e.Kind == "skill" {
			names = append(names, e.Name)
		}
	}
	if len(names) == 0 {
		return "", nil
	}
	sort.Strings(names)
	for _, name := range names {
		files, err := readSkill(filepath.Join(claudeSkills(home), name))
		if err != nil {
			continue // gone or changed by hand: drift reports it
		}
		if _, err := installSkillDir(filepath.Join(dir, "skills"), name, files); err != nil {
			return "", err
		}
	}
	meta, _ := json.MarshalIndent(map[string]string{
		"name":        pluginName,
		"description": "Skills from your MegooColab Tool Hub",
	}, "", "  ")
	if err := WriteFileAtomic(filepath.Join(dir, ".claude-plugin", "plugin.json"), meta, false); err != nil {
		return "", err
	}
	return dir, nil
}

// SafeServers are the program's hub MCP servers marked safe in read-only runs.
func SafeServers(m *Manifest, program string) []string {
	var out []string
	for _, e := range m.Entries {
		if e.Program == program && e.Kind == "mcp" && e.ReadOnlySafe {
			out = append(out, e.Name)
		}
	}
	return out
}

// MCPToolTitle matches how each adapter titles a call of an MCP tool of that server: Claude Code
// "mcp__<server>__<tool>", Codex "mcp.<server>.<tool>". A tool name never holds "__", so a server named
// "a" never matches one named "a__b".
func MCPToolTitle(server string) *regexp.Regexp {
	q := regexp.QuoteMeta(server)
	return regexp.MustCompile(`^(?:mcp__` + q + `__[A-Za-z0-9-]+(?:_[A-Za-z0-9-]+)*|mcp\.` + q + `\.[A-Za-z0-9_-]+)$`)
}
