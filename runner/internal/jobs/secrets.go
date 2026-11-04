package jobs

import (
	"regexp"
	"strings"

	acp "github.com/coder/acp-go-sdk"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// secretName is what a secret may be called; the server checks the same rules (backend/app/secrets/names.py).
var secretName = regexp.MustCompile(`^[A-Z][A-Z0-9_]{0,99}$`)

// reservedNames are variables the runner and the agent programs rely on: a secret never replaces one, even if the
// server sent it.
var reservedNames = map[string]bool{
	"PATH": true, "PATHEXT": true, "HOME": true, "USERPROFILE": true, "SYSTEMROOT": true, "SYSTEMDRIVE": true,
	"WINDIR": true, "COMSPEC": true, "TEMP": true, "TMP": true, "TMPDIR": true, "APPDATA": true, "LOCALAPPDATA": true,
	"PROGRAMDATA": true, "PROGRAMFILES": true, "SHELL": true, "USER": true, "USERNAME": true, "LOGNAME": true,
	"LANG": true, "LC_ALL": true, "PWD": true, "TERM": true, "SSH_AUTH_SOCK": true, "XDG_CONFIG_HOME": true,
	"XDG_DATA_HOME": true, "XDG_CACHE_HOME": true,
}

var reservedPrefixes = []string{"MEGOO", "ANTHROPIC_", "CLAUDE_", "OPENAI_", "CODEX_", "OMP_", "GIT_", "LC_"}

func reserved(name string) bool {
	if reservedNames[name] {
		return true
	}
	for _, p := range reservedPrefixes {
		if strings.HasPrefix(name, p) {
			return true
		}
	}
	return false
}

// usableSecrets are the run's secrets that may be set: a well-formed name the runner doesn't rely on.
func usableSecrets(secrets []protocol.RunSecret) []protocol.RunSecret {
	var out []protocol.RunSecret
	for _, s := range secrets {
		if secretName.MatchString(s.Name) && !reserved(s.Name) {
			out = append(out, s)
		}
	}
	return out
}

// secretEnv is the run's secrets as NAME=VALUE for the agent's process.
func secretEnv(secrets []protocol.RunSecret) []string {
	var env []string
	for _, s := range usableSecrets(secrets) {
		env = append(env, s.Name+"="+s.Value)
	}
	return env
}

// withSecrets adds the run's secrets to the environment of each stdio MCP server the runner hands an OMP agent (OMP
// starts them with exactly that environment).
func withSecrets(servers []acp.McpServer, secrets []protocol.RunSecret) []acp.McpServer {
	usable := usableSecrets(secrets)
	for _, srv := range servers {
		if srv.Stdio == nil {
			continue
		}
		for _, s := range usable {
			srv.Stdio.Env = append(srv.Stdio.Env, acp.EnvVariable{Name: s.Name, Value: s.Value})
		}
	}
	return servers
}

// blankText is text with the run's token and secrets replaced, for what the runner reports outside the update stream.
func (r *run) blankText(text string) string { return r.masks.Replace(text) }
