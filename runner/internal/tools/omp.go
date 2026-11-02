package tools

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// ompAgent writes MCP servers into the mcpServers of OMP's user-level mcp.json and skills into its skills/<name>/,
// both in the active OMP agent folder (OmpAgentDir). Every other key and entry of mcp.json is kept as it was.
// OMP also reads Claude Code's and Codex's skill folders; those belong to their programs and are not scanned here.
type ompAgent struct{}

func init() { register(ompAgent{}) }

func (ompAgent) Program() string { return "omp" }

// ompConfigPath asks omp for its active agent folder; tests replace it.
var ompConfigPath = func() (string, error) {
	out, err := exec.Command("omp", "config", "path").Output()
	return string(out), err
}

// OmpAgentDir is the active OMP agent folder: what `omp config path` prints, else OMP's own rule. The root is
// $PI_CONFIG_DIR or <home>/.omp; a named profile ($OMP_PROFILE, $PI_PROFILE) uses <root>/profiles/<name>/agent;
// otherwise $PI_CODING_AGENT_DIR or <root>/agent.
func OmpAgentDir(home string) string {
	if out, err := ompConfigPath(); err == nil {
		if dir := strings.TrimSpace(out); filepath.IsAbs(dir) {
			return dir
		}
	}
	root := os.Getenv("PI_CONFIG_DIR")
	if root == "" {
		root = filepath.Join(home, ".omp")
	}
	profile := os.Getenv("OMP_PROFILE")
	if profile == "" {
		profile = os.Getenv("PI_PROFILE")
	}
	if profile != "" {
		return filepath.Join(root, "profiles", profile, "agent")
	}
	if dir := os.Getenv("PI_CODING_AGENT_DIR"); dir != "" {
		return dir
	}
	return filepath.Join(root, "agent")
}

func ompMCPJSON(home string) string { return filepath.Join(OmpAgentDir(home), "mcp.json") }

func ompSkills(home string) string { return filepath.Join(OmpAgentDir(home), "skills") }

func (ompAgent) InstallMCP(home string, t Tool) (string, error) {
	if t.Mcp == nil {
		return "", fmt.Errorf("%s has no MCP setup", t.Name)
	}
	entry := claudeEntry(t.Mcp) // OMP reads the same entry shape
	err := ReplaceFile(ompMCPJSON(home), func(old []byte) ([]byte, error) {
		return editServers("mcp.json", old, func(servers map[string]json.RawMessage) error {
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

func (o ompAgent) RemoveMCP(home, name string) error {
	if _, exists, err := o.MCPFingerprint(home, name); err != nil || !exists {
		return err
	}
	return ReplaceFile(ompMCPJSON(home), func(old []byte) ([]byte, error) {
		return editServers("mcp.json", old, func(servers map[string]json.RawMessage) error {
			delete(servers, name)
			return nil
		})
	}, true)
}

func (ompAgent) MCPFingerprint(home, name string) (string, bool, error) {
	servers, err := readServersAt(ompMCPJSON(home), "mcp.json")
	if err != nil {
		return "", false, err
	}
	raw, ok := servers[name]
	if !ok {
		return "", false, nil
	}
	return fingerprintJSON(raw), true, nil
}

func (ompAgent) InstallSkill(home, name string, files []File) (string, error) {
	return installSkillDir(ompSkills(home), name, files)
}

func (ompAgent) RemoveSkill(home, name string) error { return removeSkillDir(ompSkills(home), name) }

func (ompAgent) SkillFingerprint(home, name string) (string, bool, error) {
	return skillFingerprint(filepath.Join(ompSkills(home), name))
}

func (ompAgent) ScanMCP(home string) ([]protocol.FoundTool, error) {
	servers, err := readServersAt(ompMCPJSON(home), "mcp.json")
	if err != nil {
		return nil, err
	}
	return scanServers("omp", servers), nil
}

func (ompAgent) ScanSkills(home string) ([]protocol.FoundTool, error) {
	return scanSkills("omp", ompSkills(home)), nil
}
