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

// stampFile records which skills a plugin folder was built from.
const stampFile = ".megoocolab-stamp"

// SyncPlugin makes the hub plugin hold the Claude Code skills in the manifest, copied from where they are
// installed. Nothing changed: the folder is left alone. Otherwise a new folder is built beside it and swapped
// in, so a running session never sees half a plugin; when the swap cannot happen (files held open), the old
// one stays. With no skills there is no plugin and it returns "".
func SyncPlugin(cacheRoot, home string, m *Manifest) (string, error) {
	dir := pluginDir(cacheRoot)
	var skills []Entry
	for _, e := range m.Entries {
		if e.Program == "claude_code" && e.Kind == "skill" {
			skills = append(skills, e)
		}
	}
	if len(skills) == 0 {
		_ = os.RemoveAll(dir)
		return "", nil
	}
	sort.Slice(skills, func(i, j int) bool { return skills[i].Name < skills[j].Name })
	stamp := fingerprintJSON(skills)
	if old, err := os.ReadFile(filepath.Join(dir, stampFile)); err == nil && string(old) == stamp {
		return dir, nil
	}
	if err := os.MkdirAll(cacheRoot, 0o755); err != nil {
		return "", err
	}
	next, err := os.MkdirTemp(cacheRoot, "hub-plugin.new-*")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(next) // gone after the swap
	for _, e := range skills {
		files, err := readSkill(filepath.Join(claudeSkills(home), e.Name))
		if err != nil {
			continue // gone or changed by hand: drift reports it
		}
		if _, err := installSkillDir(filepath.Join(next, "skills"), e.Name, files); err != nil {
			return "", err
		}
	}
	meta, _ := json.MarshalIndent(map[string]string{
		"name":        pluginName,
		"description": "Skills from your MegooColab Tool Hub",
	}, "", "  ")
	if err := WriteFileAtomic(filepath.Join(next, ".claude-plugin", "plugin.json"), meta, false); err != nil {
		return "", err
	}
	if err := os.WriteFile(filepath.Join(next, stampFile), []byte(stamp), 0o644); err != nil {
		return "", err
	}
	old := ""
	if _, err := os.Stat(dir); err == nil {
		old = next + ".old"
		if err := os.Rename(dir, old); err != nil {
			return PluginDir(cacheRoot), nil // in use: keep the plugin sessions already have
		}
	}
	if err := os.Rename(next, dir); err != nil {
		if old != "" {
			_ = os.Rename(old, dir)
		}
		return PluginDir(cacheRoot), err
	}
	if old != "" {
		_ = os.RemoveAll(old)
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
